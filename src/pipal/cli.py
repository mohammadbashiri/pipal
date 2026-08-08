import argparse, json, shutil, sys, subprocess
from pathlib import Path
from rich import print
from rich.prompt import Confirm, Prompt
from .registry import add_agent, rm_agent, list_agents, get_agent, migrate_registry, pipal_dir, registry_path
from .llm_config import load_llm_config
from .agent_scaffold import ensure_agent_scaffold, write_llm_json
from .runner import run_agent, run_agent_print
from .team_runner import run_team_chat
from .team_storage import create_team, list_teams, load_team, remove_team, team_dir
from .topic_summary import summarize_topic
from .topic_storage import topics_root, topic_dir, topic_sessions_dir, validate_topic_name
from .check_pi_compatibility import run_doctor


def _resolve_session_file(agent_path: str, topic_name: str, value: str) -> Path | None:
    sessions = topic_sessions_dir(agent_path, topic_name)
    direct = Path(value).expanduser()
    if direct.is_absolute():
        try:
            direct.resolve().relative_to(sessions.resolve())
        except ValueError:
            return None
        return direct.resolve() if direct.is_file() else None

    candidate = sessions / value
    if candidate.is_file():
        return candidate
    matches = [
        path
        for path in sessions.glob("*.jsonl")
        if path.stem.startswith(value) or str(_session_header(path).get("id", "")).startswith(value)
    ]
    return matches[0] if len(matches) == 1 else None


def _session_header(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.loads(handle.readline())
    except (OSError, json.JSONDecodeError):
        return {}


def build_parser():
    p = argparse.ArgumentParser(prog="pipal", add_help=True)
    sub = p.add_subparsers(dest="cmd")

    pa = sub.add_parser("agent", help="Manage agents")
    sub2 = pa.add_subparsers(dest="agent_cmd")

    p_create = sub2.add_parser("create", help="Register an agent (and create folder if missing)")
    p_create.add_argument("name")
    p_create.add_argument("path", nargs="?", default=None)
    p_create.add_argument("--type", default="default", help="Agent type (default: default)")
    p_create.add_argument("--kb", dest="kb_path", default=None, help="Knowledge base path (kbchat only)")
    p_create.add_argument(
        "--provider",
        default=None,
        help="LLM provider (noninteractive; requires --model; omit both for interactive setup)",
    )
    p_create.add_argument(
        "--model",
        default=None,
        help="LLM model (noninteractive; requires --provider; omit both for interactive setup)",
    )

    p_remove = sub2.add_parser("remove", help="Remove an agent")
    p_remove.add_argument("name")

    sub2.add_parser("list", help="List agents")

    p_chat = sub2.add_parser("chat", help="Chat with an agent (interactive TUI)")
    p_chat.add_argument("name")
    p_chat.add_argument("args", nargs=argparse.REMAINDER)

    p_ask = sub2.add_parser("ask", help="Ask an agent (one-shot prompt)")
    p_ask.add_argument("name")
    p_ask.add_argument("--print", action="store_true", dest="print_only")
    p_ask.add_argument("prompt", nargs=argparse.REMAINDER)

    p_set = sub2.add_parser("set-llm", help="Set agent llm.json")
    p_set.add_argument("name")
    p_set.add_argument("spec", nargs="?", default=None, help='Either "provider:model" or omit to use flags')
    p_set.add_argument("--provider", default=None)
    p_set.add_argument("--model", default=None)

    # ── team subcommands ──
    pteam = sub.add_parser("team", help="Create and chat with human-owned AI teams")
    team_sub = pteam.add_subparsers(dest="team_cmd")

    team_create = team_sub.add_parser("create", help="Create a team from registered Pipal agents")
    team_create.add_argument("name")
    team_create.add_argument("--manager", required=True, help="Registered agent that manages the team")
    team_create.add_argument(
        "--member",
        action="append",
        default=[],
        metavar="AGENT:ROLE",
        help="Add a member and role; repeat for multiple members",
    )
    team_create.add_argument("--owner", default="Mo", help="Human owner display name (default: Mo)")
    team_create.add_argument("--max-rounds", type=int, default=4, help="Agent delegation round budget")

    team_sub.add_parser("list", help="List teams")

    team_show = team_sub.add_parser("show", help="Show team configuration")
    team_show.add_argument("name")

    team_chat = team_sub.add_parser("chat", help="Open the multi-agent team TUI")
    team_chat.add_argument("name")
    team_chat.add_argument("--topic", default="main", help="Shared team topic (default: main)")
    team_chat.add_argument("--new-session", action="store_true", help="Start fresh native sessions")

    team_remove = team_sub.add_parser("remove", help="Remove a team and its shared topics")
    team_remove.add_argument("name")
    team_remove.add_argument("--yes", action="store_true", help="Skip confirmation")

    # ── topic subcommands ──
    ptopic = sub.add_parser("topic", help="Manage persistent Pipal topics")
    topic_sub = ptopic.add_subparsers(dest="topic_cmd")

    topic_list = topic_sub.add_parser("list", help="List topics for an agent")
    topic_list.add_argument("--agent", required=True, help="Agent name")

    topic_sum = topic_sub.add_parser("summarize", help="Update a topic's rolling summary")
    topic_sum.add_argument("--agent", required=True, help="Agent name")
    topic_sum.add_argument("--topic", dest="topic_name", default="main", help="Topic name (default: main)")

    topic_remove = topic_sub.add_parser("remove", help="Remove a topic and its pi sessions")
    topic_remove.add_argument("--agent", required=True, help="Agent name")
    topic_remove.add_argument("--topic", dest="topic_name", required=True, help="Topic name to remove")
    topic_remove.add_argument("--yes", action="store_true", help="Skip confirmation")

    # ── native pi session subcommands ──
    ps = sub.add_parser("session", help="Manage native pi sessions within a topic")
    ssub = ps.add_subparsers(dest="session_cmd")

    for command, help_text in (
        ("list", "List pi sessions in a topic"),
        ("info", "Show information about a pi session"),
        ("open", "Open a pi session"),
        ("remove", "Remove a pi session"),
    ):
        parser = ssub.add_parser(command, help=help_text)
        if command != "list":
            parser.add_argument("session", help="Session filename, path, or unique ID prefix")
        parser.add_argument("--agent", required=True, help="Agent name")
        parser.add_argument("--topic", default="main", help="Topic name (default: main)")
        if command == "remove":
            parser.add_argument("--yes", action="store_true", help="Skip confirmation")

    psrv = sub.add_parser("serve", help="Run optional local pipal HTTP/WS API")
    psrv.add_argument("--host", default="127.0.0.1")
    psrv.add_argument("--port", type=int, default=8000)
    psrv.add_argument("--agent", dest="serve_agent", default=None, help="Scope to one agent")
    psrv.add_argument("--topic", dest="serve_topic", default=None, help="Scope to one topic")
    psrv.add_argument("--session", dest="serve_session", default=None, help="Scope to one native pi session")
    psrv.add_argument("--read-only", action="store_true", help="History-only (no prompts or topic/session creation)")
    psrv.add_argument("--read-only-tools", action="store_true", help="Allow chat, restrict tools to read/grep/find/ls")

    p_doctor = sub.add_parser("check-pi-compatibility", help="Check local pi compatibility")
    p_doctor.add_argument("--agent", default=None, help="Agent to use for runtime check")

    p_uninstall = sub.add_parser("uninstall", help="Remove pipal data directory (~/.pipal)")
    p_uninstall.add_argument("--yes", action="store_true", help="Skip confirmation")

    return p

def _rollback_agent_creation(
    path: Path,
    registry_before: bytes | None,
    path_existed: bool,
    created_paths: set[Path],
) -> None:
    """Undo the filesystem and registry changes made by ``agent create``."""
    if path_existed:
        # Scaffolding is intentionally non-destructive; preserve custom files.
        for created in sorted(created_paths, key=lambda item: len(item.parts), reverse=True):
            try:
                if created.is_dir() and not created.is_symlink():
                    created.rmdir()
                else:
                    created.unlink()
            except FileNotFoundError:
                pass
    elif path.exists():
        shutil.rmtree(path)

    target = registry_path()
    if registry_before is None:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(registry_before)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    args = build_parser().parse_args(argv)

    # Validate before registry migration so an incomplete noninteractive request
    # cannot create or migrate registry files.
    if (
        args.cmd == "agent"
        and args.agent_cmd == "create"
        and bool(args.provider) != bool(args.model)
    ):
        print("[red]--provider and --model must be supplied together.[/red]")
        print("Omit both flags for interactive model selection.")
        return 2

    if migrate_registry():
        print("[green]Migrated[/green] agent registry to ~/.pipal/agents.json")

    if args.cmd == "team":
        if args.team_cmd == "create":
            if not get_agent(args.manager):
                print(f"[red]Unknown manager agent[/red] {args.manager}. Run: pipal agent list")
                return 2
            try:
                members = [parse_team_member_spec(value) for value in args.member]
            except ValueError as exc:
                print(f"[red]{exc}[/red]")
                return 2
            unknown = sorted({agent for agent, _role in members if not get_agent(agent)})
            if unknown:
                print(f"[red]Unknown team agent(s)[/red] {', '.join(unknown)}. Run: pipal agent list")
                return 2
            try:
                team = create_team(
                    args.name,
                    args.manager,
                    members,
                    owner=args.owner,
                    max_rounds=args.max_rounds,
                )
            except ValueError as exc:
                print(f"[red]{exc}[/red]")
                return 2
            print(f"[green]Created[/green] team [bold]{team['name']}[/bold]")
            print(f"[cyan]Owner[/cyan] {team['owner']}  [cyan]Manager[/cyan] @{team['manager']}")
            for member in team["members"]:
                print(f"- @{member['agent']}  {member['role']}")
            print(f"[dim]{team_dir(team['name'])}[/dim]")
            return 0

        if args.team_cmd == "list":
            teams = list_teams()
            if not teams:
                print("[yellow]No teams found[/yellow]")
                return 0
            for team in teams:
                print(
                    f"- [bold]{team.get('name', '-')}[/bold]  "
                    f"manager=@{team.get('manager', '-')}  members={len(team.get('members', []))}"
                )
            return 0

        team = load_team(getattr(args, "name", ""))
        if not team:
            print(f"[red]Unknown team[/red] {getattr(args, 'name', '')}. Run: pipal team list")
            return 2

        if args.team_cmd == "show":
            print(f"[bold]{team['name']}[/bold]")
            print(f"Owner:      {team.get('owner', '-')}")
            print(f"Manager:    @{team.get('manager', '-')}")
            print(f"Max rounds: {team.get('max_rounds', '-')}")
            print("Members:")
            for member in team.get("members", []):
                print(f"- @{member.get('agent', '-')}  {member.get('role', 'Member')}")
            print(f"Path:       {team_dir(team['name'])}")
            return 0

        if args.team_cmd == "chat":
            try:
                run_team_chat(team, args.topic, new_session=args.new_session)
            except (ValueError, FileNotFoundError) as exc:
                print(f"[red]{exc}[/red]")
                return 2
            return 0

        if args.team_cmd == "remove":
            if not args.yes and not Confirm.ask(
                f"Delete team {team['name']} and all shared topics?", default=False
            ):
                print("[yellow]Cancelled[/yellow]")
                return 0
            remove_team(team["name"])
            print(f"[green]Removed[/green] team {team['name']}")
            return 0

    if args.cmd == "topic":
        agent = get_agent(args.agent)
        if not agent:
            print(f"[red]Unknown agent[/red] {args.agent}. Run: pipal agent list")
            return 2

        if args.topic_cmd == "list":
            entries = sorted(p.name for p in topics_root(agent["path"]).iterdir() if p.is_dir())
            if not entries:
                print("[yellow]No topics found[/yellow]")
                return 0
            for name in entries:
                print(f"- {name}")
            return 0

        try:
            topic_name = validate_topic_name(args.topic_name)
        except ValueError as exc:
            print(f"[red]{exc}[/red]")
            return 2

        if args.topic_cmd == "summarize":
            llm = load_llm_config(agent["path"])
            if not llm:
                print("[yellow]No llm.json found. Run:[/yellow]")
                print(f'  pipal agent set-llm {args.agent} "provider:model"')
                return 2
            result = summarize_topic(Path(agent["path"]), topic_name, llm)
            color = "green" if result.status == "OK" else "yellow"
            print(f"[{color}]{result.status}[/{color}] {result.message}")
            return 0 if result.status in {"OK", "SKIP"} else 2

        if args.topic_cmd == "remove":
            path = topics_root(agent["path"]) / topic_name
            if not path.exists():
                print(f"[yellow]Topic not found[/yellow] {topic_name}")
                return 0
            if not args.yes and not Confirm.ask(f"Delete topic {topic_name} and all its sessions?", default=False):
                print("[yellow]Cancelled[/yellow]")
                return 0
            shutil.rmtree(path)
            print(f"[green]Removed[/green] topic {topic_name}")
            return 0

    if args.cmd == "session":
        agent = get_agent(args.agent)
        if not agent:
            print(f"[red]Unknown agent[/red] {args.agent}. Run: pipal agent list")
            return 2
        try:
            sessions = topic_sessions_dir(agent["path"], args.topic)
        except ValueError as exc:
            print(f"[red]{exc}[/red]")
            return 2

        if args.session_cmd == "list":
            files = sorted(sessions.glob("*.jsonl"), reverse=True)
            if not files:
                print("[yellow]No sessions found[/yellow]")
                return 0
            for path in files:
                header = _session_header(path)
                session_id = header.get("id", "-")
                print(f"- {path.name}  id={session_id}")
            return 0

        session_file = _resolve_session_file(agent["path"], args.topic, args.session)
        if not session_file:
            print(f"[red]Session not found or ambiguous[/red] {args.session}")
            return 2

        if args.session_cmd == "info":
            header = _session_header(session_file)
            entries = max(0, len(session_file.read_text(encoding="utf-8").splitlines()) - 1)
            print(f"File:    {session_file}")
            print(f"ID:      {header.get('id', '-')}")
            print(f"Created: {header.get('timestamp', '-')}")
            print(f"CWD:     {header.get('cwd', '-')}")
            print(f"Entries: {entries}")
            return 0

        if args.session_cmd == "open":
            llm = load_llm_config(agent["path"])
            if not llm:
                print("[yellow]No llm.json found[/yellow]")
                return 2
            run_agent(agent["path"], llm, ["--topic", args.topic, "--session", str(session_file)])
            return 0

        if args.session_cmd == "remove":
            if not args.yes and not Confirm.ask(f"Delete pi session {session_file.name}?", default=False):
                print("[yellow]Cancelled[/yellow]")
                return 0
            session_file.unlink()
            print(f"[green]Removed[/green] {session_file.name}")
            return 0

    if args.cmd == "serve":
        from .server import run_server

        return run_server(
            host=args.host,
            port=args.port,
            agent=args.serve_agent,
            topic=args.serve_topic,
            session=args.serve_session,
            read_only=args.read_only,
            read_only_tools=args.read_only_tools,
        )

    if args.cmd == "check-pi-compatibility":
        return run_doctor(args.agent)

    if args.cmd == "uninstall":
        base = pipal_dir()

        remove_data = args.yes or Confirm.ask(
            f"Remove pipal data directory {base}?", default=False
        )
        if remove_data:
            if base.exists():
                shutil.rmtree(base)
                print(f"[green]Removed[/green] {base}")
            else:
                print("[yellow]No pipal data found[/yellow]")

        remove_cli = args.yes or Confirm.ask(
            "Uninstall pipal CLI via 'uv tool uninstall pipal'?", default=False
        )
        if remove_cli:
            uv = shutil.which("uv")
            if not uv:
                print("[red]uv not found[/red]. Run: uv tool uninstall pipal")
                return 2
            result = subprocess.run([uv, "tool", "uninstall", "pipal"])
            return result.returncode

        return 0

    if args.cmd == "agent":
        if args.agent_cmd == "create":
            allowed_types = {"default", "kbchat"}
            if args.type not in allowed_types:
                print(f"[red]Unknown agent type[/red] {args.type}")
                print("Valid types: default, kbchat")
                return 2

            path_obj = (Path(args.path or str(pipal_dir() / "agents")) / args.name).expanduser().resolve()
            path = str(path_obj)
            path_existed = path_obj.exists()
            before_paths = set(path_obj.rglob("*")) if path_existed and path_obj.is_dir() else set()
            llm_path = path_obj / "llm.json"
            llm_existed = llm_path.is_file()
            llm_before = llm_path.read_bytes() if llm_existed else None
            reg_file = registry_path()
            registry_before = reg_file.read_bytes() if reg_file.exists() else None
            try:
                path_obj.mkdir(parents=True, exist_ok=True)
                res = add_agent(args.name, path)  # should auto-create registry
                if isinstance(res, dict) and res.get("registry_created"):
                    print("[green]Created[/green] ~/.pipal/agents.json")
                    print(f"[green]Registered[/green] {args.name} → {res['path']}")
                else:
                    p = res["path"] if isinstance(res, dict) else res
                    print(f"[green]Registered[/green] {args.name} → {p}")

                print(f"[green]Ensured directory[/green] {path}")
                ensure_agent_scaffold(
                    path,
                    name=args.name,
                    template=args.type,
                    kb_path=args.kb_path,
                    agent_type=args.type if args.type != "default" else None,
                )

                if args.provider and args.model:
                    written = write_llm_json(path, args.provider, args.model)
                    print(f"[green]LLM[/green] provider={args.provider} model={args.model}")
                elif _interactive_set_llm(path, args.name):
                    return 0
                else:
                    print("[red]Model selection required.[/red]")
                    print("Run `pi` and complete /login, then try again.")
                    raise ValueError("Model selection required")
                return 0
            except Exception as exc:
                current_paths = set(path_obj.rglob("*")) if path_obj.exists() else set()
                _rollback_agent_creation(path_obj, registry_before, path_existed, current_paths - before_paths)
                if llm_existed:
                    llm_path.write_bytes(llm_before)
                elif llm_path.is_file() or llm_path.is_symlink():
                    try:
                        llm_path.unlink()
                    except FileNotFoundError:
                        pass
                if str(exc) != "Model selection required":
                    print(f"[red]Agent creation failed; rolled back:[/red] {exc}")
                return 2

        if args.agent_cmd == "remove":
            path = rm_agent(args.name)
            if path is None:
                print("[yellow]Not found[/yellow]")
                return 0
            print(f"[green]OK[/green] unregistered {args.name}")
            if Path(path).exists():
                answer = input(f"Also delete agent directory {path}? [y/N] ").strip().lower()
                if answer in ("y", "yes"):
                    shutil.rmtree(path)
                    print(f"[green]Deleted[/green] {path}")
            return 0

        if args.agent_cmd == "list":
            agents = list_agents()
            if not agents:
                print("[yellow]No agents registered[/yellow]")
                return 0
            for name, p in agents.items():
                print(f"- [bold]{name}[/bold]  {p}")
            return 0

        if args.agent_cmd == "chat":
            a = get_agent(args.name)
            if not a:
                print(f"[red]Unknown agent[/red] {args.name}. Run: pipal agent list")
                return 2

            llm = load_llm_config(a["path"])
            if not llm:
                print("[yellow]No llm.json found. Run:[/yellow]")
                print(f'  pipal agent set-llm {args.name} "provider:model"')
                return 2

            extra_args = args.args or []
            try:
                run_agent(a["path"], llm, extra_args)
            except ValueError as exc:
                print(f"[red]{exc}[/red]")
                return 2
            return 0

        if args.agent_cmd == "ask":
            a = get_agent(args.name)
            if not a:
                print(f"[red]Unknown agent[/red] {args.name}. Run: pipal agent list")
                return 2

            llm = load_llm_config(a["path"])
            if not llm:
                print("[yellow]No llm.json found. Run:[/yellow]")
                print(f'  pipal agent set-llm {args.name} "provider:model"')
                return 2

            prompt = args.prompt or []
            print_only = args.print_only
            if prompt and prompt[0] in {"-p", "--print"}:
                print_only = True
                prompt = prompt[1:]

            if not prompt:
                print("[red]Missing prompt.[/red] Usage: pipal agent ask <name> \"...\"")
                return 2

            if print_only:
                response = run_agent_print(a["path"], llm, " ".join(prompt))
                if response:
                    print(response)
                return 0

            try:
                run_agent(a["path"], llm, prompt)
            except ValueError as exc:
                print(f"[red]{exc}[/red]")
                return 2
            return 0
        
        if args.agent_cmd == "set-llm":
            a = get_agent(args.name)
            if not a:
                print(f"[red]Unknown agent[/red] {args.name}. Run: pipal agent list")
                return 2

            provider = args.provider
            model = args.model

            if args.spec:
                try:
                    provider, model = parse_llm_spec(args.spec)
                except Exception as e:
                    print(f"[red]{e}[/red]")
                    return 2

            if not provider or not model:
                if _interactive_set_llm(a["path"], args.name):
                    return 0
                print("[red]Model selection required.[/red]")
                return 2

            written = write_llm_json(a["path"], provider, model)
            print(f"[green]Updated[/green] {written}")
            print(f"[cyan]LLM[/cyan] provider={provider} model={model}")
            return 0

    print("[yellow]Tip:[/yellow] use `pipal agent ...`")
    return 0

def parse_team_member_spec(spec: str) -> tuple[str, str]:
    if not spec or ":" not in spec:
        raise ValueError('Invalid member. Expected "agent:role".')
    agent, role = spec.split(":", 1)
    agent, role = agent.strip(), role.strip()
    if not agent or not role:
        raise ValueError('Invalid member. Expected "agent:role".')
    return agent, role


def parse_llm_spec(spec: str):
    if not spec or ":" not in spec:
        raise ValueError('Invalid spec. Expected "provider:model".')
    provider, model = spec.split(":", 1)
    provider, model = provider.strip(), model.strip()
    if not provider or not model:
        raise ValueError('Invalid spec. Expected "provider:model".')
    return provider, model


def _interactive_set_llm(agent_path: str, name: str) -> bool:
    """Interactive model selection. Returns True if llm.json written."""
    try:
        result = subprocess.run(
            ["pi", "--list-models"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("[red]pi not found.[/red] Install with: npm install -g @earendil-works/pi-coding-agent")
        return False

    if result.returncode != 0 or not result.stdout:
        print("[yellow]No models available.[/yellow] Run `pi` and complete /login, then try again.")
        return False

    lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
    if len(lines) < 2:
        return False

    rows = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        provider, model = parts[0], parts[1]
        rows.append((provider, model))

    if not rows:
        return False

    providers = sorted({p for p, _ in rows})
    print("\n[bold]Select provider[/bold]")
    for i, p in enumerate(providers, 1):
        print(f"  {i}. {p}")

    while True:
        provider_choice = Prompt.ask("Provider").strip()
        if not provider_choice:
            print("[red]Provider is required[/red]")
            continue
        if provider_choice.isdigit():
            idx = int(provider_choice) - 1
            if idx < 0 or idx >= len(providers):
                print("[red]Invalid provider selection[/red]")
                continue
            provider = providers[idx]
            break
        if provider_choice in providers:
            provider = provider_choice
            break
        print("[red]Unknown provider[/red]")

    models = [m for p, m in rows if p == provider]
    print(f"\n[bold]Select model[/bold] ({provider})")
    for i, m in enumerate(models, 1):
        print(f"  {i}. {m}")

    while True:
        model_choice = Prompt.ask("Model").strip()
        if not model_choice:
            print("[red]Model is required[/red]")
            continue
        if model_choice.isdigit():
            idx = int(model_choice) - 1
            if idx < 0 or idx >= len(models):
                print("[red]Invalid model selection[/red]")
                continue
            model = models[idx]
            break
        if model_choice in models:
            model = model_choice
            break
        print("[red]Unknown model[/red]")

    written = write_llm_json(agent_path, provider, model)
    print(f"[green]Updated[/green] {written}")
    print(f"[cyan]LLM[/cyan] provider={provider} model={model}")
    return True
