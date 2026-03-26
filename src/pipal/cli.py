import argparse, shutil, sys, subprocess
from pathlib import Path
from rich import print
from rich.prompt import Confirm, Prompt
from rich.table import Table
from .registry import add_agent, rm_agent, list_agents, get_agent, migrate_registry, pipal_dir
from .llm_config import load_llm_config
from .agent_scaffold import ensure_agent_scaffold, write_llm_json
from .runner import run_agent, run_agent_print
from .daemon import start_daemon, stop_daemon, daemon_status, daemon_logs, parse_interval, format_interval, format_uptime
from .session_summary import summarize_session
from .check_pi_compatibility import run_doctor
from .tasks import (
    list_tasks,
    load_task,
    append_run_log,
    last_run,
    parse_task_response,
    parse_task_message,
    remove_task,
    task_id_from_title,
    task_root_global,
    task_root_personal,
)


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

    # ── session subcommands ──
    ps = sub.add_parser("session", help="Manage sessions")
    ssub = ps.add_subparsers(dest="session_cmd")

    s_list = ssub.add_parser("list", help="List sessions for an agent")
    s_list.add_argument("--agent", required=True, help="Agent name")

    s_sum = ssub.add_parser("summarize", help="Summarize the latest session into summary.md")
    s_sum.add_argument("--agent", required=True, help="Agent name")
    s_sum.add_argument("--session", dest="session_name", default=None, help="Session name (defaults to main)")

    s_remove = ssub.add_parser("remove", help="Remove a session folder")
    s_remove.add_argument("--agent", required=True, help="Agent name")
    s_remove.add_argument("--session", dest="session_name", required=True, help="Session name to remove")
    s_remove.add_argument("--yes", action="store_true", help="Skip confirmation")

    # ── task subcommands ──
    pt = sub.add_parser("task", help="Manage tasks")
    tsub = pt.add_subparsers(dest="task_cmd")

    t_list = tsub.add_parser("list", help="List tasks")
    t_list.add_argument("--agent", default=None, help="Agent name (list personal tasks)")
    t_list.add_argument("--global", dest="global_only", action="store_true", help="List global tasks only")

    t_run = tsub.add_parser("run", help="Run a task")
    t_run.add_argument("task_id")
    t_run.add_argument("--agent", default=None, help="Agent name (personal task)")

    t_status = tsub.add_parser("status", help="Show task status")
    t_status.add_argument("--agent", default=None, help="Agent name (list personal tasks)")
    t_status.add_argument("--global", dest="global_only", action="store_true", help="Show global tasks only")

    t_remove = tsub.add_parser("remove", help="Remove a task")
    t_remove.add_argument("task_id")
    t_remove.add_argument("--agent", default=None, help="Agent name (personal task)")
    t_remove.add_argument("--global", dest="global_only", action="store_true", help="Remove a global task")

    # ── daemon subcommands ──
    pd = sub.add_parser("daemon", help="Manage agent daemon")
    dsub = pd.add_subparsers(dest="daemon_cmd")

    pd_start = dsub.add_parser("start", help="Start heartbeat daemon")
    pd_start.add_argument("--agent", required=True, help="Agent name")
    pd_start.add_argument("--every", required=True, help='Interval, e.g. "30m", "1h"')

    pd_stop = dsub.add_parser("stop", help="Stop heartbeat daemon")
    pd_stop.add_argument("--agent", required=True, help="Agent name")

    pd_status = dsub.add_parser("status", help="Check daemon status")
    pd_status.add_argument("--agent", default=None, help="Agent name")
    pd_status.add_argument("--all", action="store_true", help="Show status for all agents")

    pd_logs = dsub.add_parser("logs", help="Show daemon logs")
    pd_logs.add_argument("--agent", required=True, help="Agent name")
    pd_logs.add_argument("-n", type=int, default=50, help="Number of lines (default: 50)")

    psrv = sub.add_parser("serve", help="Run pipal HTTP/WS server")
    psrv.add_argument("--host", default="0.0.0.0")
    psrv.add_argument("--port", type=int, default=8000)
    psrv.add_argument("--agent", dest="serve_agent", default=None, help="Scope to one agent")
    psrv.add_argument("--session", dest="serve_session", default=None, help="Scope to one session")
    psrv.add_argument("--session-file", dest="serve_session_file", default=None, help="Scope to one session file")
    psrv.add_argument("--read-only", action="store_true", help="History-only (no prompts, no new sessions)")
    psrv.add_argument("--read-only-tools", action="store_true", help="Allow chat + sessions, restrict tools to read/grep/find/ls")

    p_doctor = sub.add_parser("check-pi-compatibility", help="Check local pi compatibility")
    p_doctor.add_argument("--agent", default=None, help="Agent to use for runtime check")

    p_uninstall = sub.add_parser("uninstall", help="Remove pipal data directory (~/.pipal)")
    p_uninstall.add_argument("--yes", action="store_true", help="Skip confirmation")

    return p

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    if migrate_registry():
        print("[green]Migrated[/green] agent registry to ~/.pipal/agents.json")

    args = build_parser().parse_args(argv)

    if args.cmd == "session":
        if args.session_cmd == "list":
            agent = get_agent(args.agent)
            if not agent:
                print(f"[red]Unknown agent[/red] {args.agent}. Run: pipal agent list")
                return 2

            sessions_root = Path(agent["path"]) / "sessions"
            if not sessions_root.exists():
                print("[yellow]No sessions found[/yellow]")
                return 0

            session_names = sorted(p.name for p in sessions_root.iterdir() if p.is_dir())
            if not session_names:
                print("[yellow]No sessions found[/yellow]")
                return 0

            for name in session_names:
                print(f"- {name}")
            return 0

        if args.session_cmd == "summarize":
            agent = get_agent(args.agent)
            if not agent:
                print(f"[red]Unknown agent[/red] {args.agent}. Run: pipal agent list")
                return 2

            llm = load_llm_config(agent["path"])
            if not llm:
                print("[yellow]No llm.json found. Run:[/yellow]")
                print(f'  pipal agent set-llm {args.agent} "provider:model"')
                return 2

            result = summarize_session(Path(agent["path"]), args.session_name, llm)
            if result.status == "OK":
                print(f"[green]OK[/green] {result.message}")
                return 0
            if result.status == "SKIP":
                print(f"[yellow]SKIP[/yellow] {result.message}")
                return 0
            print(f"[red]FAIL[/red] {result.message}")
            return 2

        if args.session_cmd == "remove":
            agent = get_agent(args.agent)
            if not agent:
                print(f"[red]Unknown agent[/red] {args.agent}. Run: pipal agent list")
                return 2

            session_dir = Path(agent["path"]) / "sessions" / args.session_name
            if not session_dir.exists():
                print(f"[yellow]Session not found[/yellow] {session_dir}")
                return 0

            if not args.yes:
                if not Confirm.ask(f"Delete session directory {session_dir}?", default=False):
                    print("[yellow]Cancelled[/yellow]")
                    return 0

            shutil.rmtree(session_dir)
            print(f"[green]Removed[/green] {session_dir}")
            return 0

    if args.cmd == "serve":
        from .server import run_server

        return run_server(
            host=args.host,
            port=args.port,
            agent=args.serve_agent,
            session=args.serve_session,
            session_file=args.serve_session_file,
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
                for agent_name, agent_path in list_agents().items():
                    if stop_daemon(agent_path):
                        print(f"[green]Stopped[/green] daemon for [bold]{agent_name}[/bold]")
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

    if args.cmd == "task":

        if args.task_cmd == "list":
            if args.agent and args.global_only:
                print("[red]Use either --agent or --global, not both.[/red]")
                return 2

            entries = []
            if args.agent:
                agent = get_agent(args.agent)
                if not agent:
                    print(f"[red]Unknown agent[/red] {args.agent}. Run: pipal agent list")
                    return 2
                root = task_root_personal(agent["path"])
                tasks = list_tasks(root)
                entries.extend(("personal", agent["name"], name, path) for name, path in tasks)
            elif args.global_only:
                root = task_root_global()
                tasks = list_tasks(root)
                entries.extend(("global", None, name, path) for name, path in tasks)
            else:
                tasks = list_tasks(task_root_global())
                entries.extend(("global", None, name, path) for name, path in tasks)
                for agent_name, agent_path in list_agents().items():
                    tasks = list_tasks(task_root_personal(agent_path))
                    entries.extend(("personal", agent_name, name, path) for name, path in tasks)

            if not entries:
                print("[yellow]No tasks found[/yellow]")
                return 0

            for scope, agent_name, name, path in entries:
                scope_label = "global" if scope == "global" else f"personal({agent_name})"
                print(f"- {name} [{scope_label}]  {path}")
            return 0

        if args.task_cmd == "run":
            agent = None
            if args.agent:
                agent = get_agent(args.agent)
                if not agent:
                    print(f"[red]Unknown agent[/red] {args.agent}. Run: pipal agent list")
                    return 2
                root = task_root_personal(agent["path"])
            else:
                root = task_root_global()

            task_dir = root / args.task_id
            if not task_dir.exists():
                alt_id = task_id_from_title(args.task_id)
                task_dir = root / alt_id

            task_file = task_dir / "task.md"
            if not task_file.exists():
                print(f"[red]Task not found[/red] {task_file}")
                return 2

            task = load_task(task_file)
            if not agent:
                assigned_to = task.get("assigned_to")
                if not assigned_to:
                    print("[red]Task has no assigned_to. Specify --agent or set assigned_to in frontmatter.[/red]")
                    return 2
                agent = get_agent(assigned_to)
                if not agent:
                    print(f"[red]Unknown agent[/red] {assigned_to}. Run: pipal agent list")
                    return 2

            llm = load_llm_config(agent["path"])
            if not llm:
                print("[yellow]No llm.json found. Run:[/yellow]")
                print(f'  pipal agent set-llm {agent["name"]} "provider:model"')
                return 2

            llm_run = dict(llm)
            task_provider = task.get("provider")
            task_model = task.get("model")
            if task_provider:
                llm_run["provider"] = task_provider
            if task_model:
                llm_run["model"] = task_model

            task_content = task_file.read_text(encoding="utf-8")
            prompt = (
                "TASK FILE:\n"
                "---\n"
                f"{task_content}\n"
                "---\n\n"
                "Execute only the task above. Use tools/files as needed to complete it. "
                "Reply in exactly one line using one of these formats: "
                "TASK_OK changes=\"...\" next_steps=\"...\" or "
                "TASK_FAIL reason=\"...\"."
            )
            response = run_agent_print(agent["path"], llm_run, prompt)
            status, message = parse_task_response(response)
            log_path = append_run_log(task_file.parent, status, message)

            print(f"{status} {message}")
            print(f"[cyan]Logged[/cyan] {log_path}")
            return 0

        if args.task_cmd == "status":
            if args.agent and args.global_only:
                print("[red]Use either --agent or --global, not both.[/red]")
                return 2

            entries = []
            if args.agent:
                agent = get_agent(args.agent)
                if not agent:
                    print(f"[red]Unknown agent[/red] {args.agent}. Run: pipal agent list")
                    return 2
                tasks = list_tasks(task_root_personal(agent["path"]))
                entries.extend(("personal", agent["name"], name, path) for name, path in tasks)
            elif args.global_only:
                tasks = list_tasks(task_root_global())
                entries.extend(("global", None, name, path) for name, path in tasks)
            else:
                tasks = list_tasks(task_root_global())
                entries.extend(("global", None, name, path) for name, path in tasks)
                for agent_name, agent_path in list_agents().items():
                    tasks = list_tasks(task_root_personal(agent_path))
                    entries.extend(("personal", agent_name, name, path) for name, path in tasks)

            if not entries:
                print("[yellow]No tasks found[/yellow]")
                return 0

            table = Table(show_header=True, header_style="bold", show_lines=True)
            table.add_column("ID", no_wrap=True)
            table.add_column("Scope", no_wrap=True)
            table.add_column("Title", overflow="fold")
            table.add_column("Status", no_wrap=True)
            table.add_column("Assigned", no_wrap=True)
            table.add_column("Schedule", no_wrap=True)
            table.add_column("Last Run", no_wrap=True)
            table.add_column("Result", overflow="fold")

            for scope, agent_name, name, path in entries:
                task = load_task(path)
                last = last_run(path.parent)
                status = task.get("status") or "-"
                assigned_to = task.get("assigned_to") or "-"
                schedule = task.get("schedule") or "-"
                title = task.get("title") or name
                scope_label = "global" if scope == "global" else f"personal({agent_name})"

                if last:
                    parsed = parse_task_message(last["status"], last["message"])
                    last_run_ts = last["timestamp"]
                    if parsed["status"] == "TASK_OK":
                        result = f"OK changes={parsed.get('changes') or '-'} next_steps={parsed.get('next_steps') or '-'}"
                    else:
                        result = f"FAIL reason={parsed.get('reason') or parsed.get('raw') or '-'}"
                else:
                    last_run_ts = "-"
                    result = "-"

                table.add_row(
                    name,
                    scope_label,
                    title,
                    status,
                    assigned_to,
                    schedule,
                    last_run_ts,
                    result,
                )

            print(table)
            return 0

        if args.task_cmd == "remove":
            if args.agent and args.global_only:
                print("[red]Use either --agent or --global, not both.[/red]")
                return 2

            if args.agent:
                agent = get_agent(args.agent)
                if not agent:
                    print(f"[red]Unknown agent[/red] {args.agent}. Run: pipal agent list")
                    return 2
                root = task_root_personal(agent["path"])
            elif args.global_only:
                root = task_root_global()
            else:
                print("[red]Specify --agent or --global to remove a task.[/red]")
                return 2

            task_dir = root / args.task_id
            if not task_dir.exists():
                alt_id = task_id_from_title(args.task_id)
                task_dir = root / alt_id

            if not task_dir.exists():
                print(f"[yellow]Task not found[/yellow] {task_dir}")
                return 0

            if not Confirm.ask(f"Delete task directory {task_dir}?", default=False):
                print("[yellow]Cancelled[/yellow]")
                return 0

            remove_task(task_dir)
            print(f"[green]Removed[/green] {task_dir}")
            return 0

    if args.cmd == "agent":
        if args.agent_cmd == "create":
            allowed_types = {"default", "kbchat"}
            if args.type not in allowed_types:
                print(f"[red]Unknown agent type[/red] {args.type}")
                print("Valid types: default, kbchat")
                return 2

            base = args.path or str(pipal_dir() / "agents")
            path = str((Path(base) / args.name).expanduser().resolve())
            Path(path).mkdir(parents=True, exist_ok=True)

            res = add_agent(args.name, path)  # should auto-create registry
            if isinstance(res, dict) and res.get("registry_created"):
                print("[green]Created[/green] ~/.pipal/agents.json")
                print(f"[green]Registered[/green] {args.name} → {res['path']}")
            else:
                # if your add_agent returns just a path string
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

            if _interactive_set_llm(path, args.name):
                return 0

            print("[red]Model selection required.[/red]")
            print("Run `pi` and complete /login, then try again.")
            return 2

        if args.agent_cmd == "remove":
            a = get_agent(args.name)
            if a and stop_daemon(a["path"]):
                print(f"[green]Stopped[/green] daemon for [bold]{args.name}[/bold]")

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
            run_agent(a["path"], llm, extra_args)
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

            run_agent(a["path"], llm, prompt)
            return 0
        
        if args.agent_cmd == "set-llm":
            a = get_agent(args.name)
            if not a:
                print(f"[red]Unknown agent[/red] {args.name}. Run: pipal agent list")
                return 2

            ensure_agent_scaffold(a["path"], name=args.name)

            provider = args.provider
            model = args.model

            if args.spec:
                try:
                    provider, model = parse_llm_spec(args.spec)
                except Exception as e:
                    print(f"[red]{e}[/red]")
                    return 2

            if not provider or not model:
                print("[red]Missing model info.[/red] Use either:")
                print(f'  pipal agent set-llm {args.name} --provider ollama --model "Mistral:7b"')
                print(f'  pipal agent set-llm {args.name} "ollama:Mistral:7b"')
                return 2

            written = write_llm_json(a["path"], provider, model)
            print(f"[green]Updated[/green] {written}")
            print(f"[cyan]LLM[/cyan] provider={provider} model={model}")
            return 0

    if args.cmd == "daemon":
        if args.daemon_cmd == "start":
            a = get_agent(args.agent)
            if not a:
                print(f"[red]Unknown agent[/red] {args.agent}. Run: pipal agent list")
                return 2
            try:
                interval = parse_interval(args.every)
            except ValueError as e:
                print(f"[red]{e}[/red]")
                return 2
            try:
                pid = start_daemon(args.agent, a["path"], interval)
            except RuntimeError as e:
                print(f"[yellow]{e}[/yellow]")
                return 1
            except FileNotFoundError as e:
                print(f"[red]{e}[/red]")
                return 2
            print(f"[green]Daemon started[/green] for [bold]{args.agent}[/bold]")
            print(f"  PID:      {pid}")
            print(f"  interval: {format_interval(interval)}")
            print(f"  log:      {Path(a['path']) / 'daemon.log'}")
            return 0

        if args.daemon_cmd == "stop":
            a = get_agent(args.agent)
            if not a:
                print(f"[red]Unknown agent[/red] {args.agent}. Run: pipal agent list")
                return 2
            if stop_daemon(a["path"]):
                print(f"[green]Stopped[/green] daemon for [bold]{args.agent}[/bold]")
            else:
                print(f"[yellow]No daemon running for[/yellow] {args.agent}")
            return 0

        if args.daemon_cmd == "status":
            if args.agent and args.all:
                print("[red]Use either --agent or --all, not both.[/red]")
                return 2

            if args.agent:
                agents = {args.agent: get_agent(args.agent)}
                if not agents[args.agent]:
                    print(f"[red]Unknown agent[/red] {args.agent}. Run: pipal agent list")
                    return 2
            else:
                agents = list_agents()
                if not agents:
                    print("[yellow]No agents registered[/yellow]")
                    return 0

            for name, path in agents.items():
                a_path = path if isinstance(path, str) else path.get("path")
                if not a_path:
                    continue
                st = daemon_status(a_path)
                if not st:
                    print(f"{name} daemon: [yellow]stopped[/yellow]")
                    continue
                print(f"{name} daemon: [green]running[/green]")
                print(f"  PID:            {st['pid']}")
                if st.get('started_at'):
                    print(f"  uptime:         {format_uptime(st['started_at'])}")
                if st.get('interval'):
                    print(f"  interval:       {format_interval(st['interval'])}")
                if st.get('last_heartbeat'):
                    print(f"  last heartbeat: {st['last_heartbeat']}")
                else:
                    print(f"  last heartbeat: (none yet)")
                print(f"  log:            {st['log']}")
            return 0

        if args.daemon_cmd == "logs":
            a = get_agent(args.agent)
            if not a:
                print(f"[red]Unknown agent[/red] {args.agent}. Run: pipal agent list")
                return 2
            output = daemon_logs(a["path"], lines=args.n)
            if output:
                print(output)
            else:
                print("[yellow]No logs yet[/yellow]")
            return 0

    print("[yellow]Tip:[/yellow] use `pipal agent ...`")
    return 0

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
        print("[red]pi not found.[/red] Install with: npm install -g @mariozechner/pi-coding-agent")
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


