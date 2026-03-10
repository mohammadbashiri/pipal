import argparse, shutil, sys
from pathlib import Path
from rich import print
from rich.prompt import Confirm, Prompt
from .registry import add_agent, rm_agent, list_agents, get_agent
from .llm_config import load_llm_config
from .agent_scaffold import ensure_agent_scaffold, write_llm_json
from .runner import run_agent
from .daemon import start_daemon, stop_daemon, daemon_status, daemon_logs, parse_interval, format_interval, format_uptime


def build_parser():
    p = argparse.ArgumentParser(prog="pal", add_help=True)
    sub = p.add_subparsers(dest="cmd")

    pa = sub.add_parser("agent", help="Manage agents")
    sub2 = pa.add_subparsers(dest="agent_cmd")

    p_create = sub2.add_parser("create", help="Register an agent (and create folder if missing)")
    p_create.add_argument("name")
    p_create.add_argument("path", nargs="?", default=None)

    p_remove = sub2.add_parser("remove", help="Remove an agent")
    p_remove.add_argument("name")

    sub2.add_parser("list", help="List agents")

    p_chat = sub2.add_parser("chat", help="Chat with an agent (interactive TUI)")
    p_chat.add_argument("name")
    p_chat.add_argument("args", nargs=argparse.REMAINDER)

    p_ask = sub2.add_parser("ask", help="Ask an agent (one-shot prompt)")
    p_ask.add_argument("name")
    p_ask.add_argument("prompt", nargs=argparse.REMAINDER)

    p_set = sub2.add_parser("set-llm", help="Set agent llm.json")
    p_set.add_argument("name")
    p_set.add_argument("spec", nargs="?", default=None, help='Either "provider:model" or omit to use flags')
    p_set.add_argument("--provider", default=None)
    p_set.add_argument("--model", default=None)

    # ── daemon subcommands ──
    pd = sub.add_parser("daemon", help="Manage agent daemon")
    dsub = pd.add_subparsers(dest="daemon_cmd")

    pd_start = dsub.add_parser("start", help="Start heartbeat daemon")
    pd_start.add_argument("--agent", required=True, help="Agent name")
    pd_start.add_argument("--every", required=True, help='Interval, e.g. "30m", "1h"')

    pd_stop = dsub.add_parser("stop", help="Stop heartbeat daemon")
    pd_stop.add_argument("--agent", required=True, help="Agent name")

    pd_status = dsub.add_parser("status", help="Check daemon status")
    pd_status.add_argument("--agent", required=True, help="Agent name")

    pd_logs = dsub.add_parser("logs", help="Show daemon logs")
    pd_logs.add_argument("--agent", required=True, help="Agent name")
    pd_logs.add_argument("-n", type=int, default=50, help="Number of lines (default: 50)")

    return p

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    args = build_parser().parse_args(argv)

    if args.cmd == "agent":
        if args.agent_cmd == "create":
            base = args.path or "."
            path = str((Path(base) / args.name).expanduser().resolve())
            Path(path).mkdir(parents=True, exist_ok=True)

            res = add_agent(args.name, path)  # should auto-create registry
            if isinstance(res, dict) and res.get("registry_created"):
                print("[green]Created[/green] ~/.pi/agents.json")
                print(f"[green]Registered[/green] {args.name} → {res['path']}")
            else:
                # if your add_agent returns just a path string
                p = res["path"] if isinstance(res, dict) else res
                print(f"[green]Registered[/green] {args.name} → {p}")

            print(f"[green]Ensured directory[/green] {path}")

            ensure_agent_scaffold(path, name=args.name)

            print(f"[dim]Set model with:[/dim]")
            print(f"[dim]pal agent set-llm {args.name} \"provider:model\"[/dim]")


            return 0

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
                print(f"[red]Unknown agent[/red] {args.name}. Run: pal agent list")
                return 2

            llm = load_llm_config(a["path"])
            if not llm:
                print("[yellow]No llm.json found. Run:[/yellow]")
                print(f'  pal agent set-llm {args.name} "provider:model"')
                return 2

            extra_args = args.args or []
            run_agent(a["path"], llm, extra_args)
            return 0

        if args.agent_cmd == "ask":
            a = get_agent(args.name)
            if not a:
                print(f"[red]Unknown agent[/red] {args.name}. Run: pal agent list")
                return 2

            llm = load_llm_config(a["path"])
            if not llm:
                print("[yellow]No llm.json found. Run:[/yellow]")
                print(f'  pal agent set-llm {args.name} "provider:model"')
                return 2

            if not args.prompt:
                print("[red]Missing prompt.[/red] Usage: pal agent ask <name> \"...\"")
                return 2

            extra_args = args.prompt or []
            run_agent(a["path"], llm, extra_args)
            return 0
        
        if args.agent_cmd == "set-llm":
            a = get_agent(args.name)
            if not a:
                print(f"[red]Unknown agent[/red] {args.name}. Run: pal agent list")
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
                print(f'  pal agent set-llm {args.name} --provider ollama --model "Mistral:7b"')
                print(f'  pal agent set-llm {args.name} "ollama:Mistral:7b"')
                return 2

            written = write_llm_json(a["path"], provider, model)
            print(f"[green]Updated[/green] {written}")
            print(f"[cyan]LLM[/cyan] provider={provider} model={model}")
            return 0

    if args.cmd == "daemon":
        if args.daemon_cmd == "start":
            a = get_agent(args.agent)
            if not a:
                print(f"[red]Unknown agent[/red] {args.agent}. Run: pal agent list")
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
                print(f"[red]Unknown agent[/red] {args.agent}. Run: pal agent list")
                return 2
            if stop_daemon(a["path"]):
                print(f"[green]Stopped[/green] daemon for [bold]{args.agent}[/bold]")
            else:
                print(f"[yellow]No daemon running for[/yellow] {args.agent}")
            return 0

        if args.daemon_cmd == "status":
            a = get_agent(args.agent)
            if not a:
                print(f"[red]Unknown agent[/red] {args.agent}. Run: pal agent list")
                return 2
            st = daemon_status(a["path"])
            if not st:
                print(f"{args.agent} daemon: [yellow]stopped[/yellow]")
                return 0
            print(f"{args.agent} daemon: [green]running[/green]")
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
                print(f"[red]Unknown agent[/red] {args.agent}. Run: pal agent list")
                return 2
            output = daemon_logs(a["path"], lines=args.n)
            if output:
                print(output)
            else:
                print("[yellow]No logs yet[/yellow]")
            return 0

    print("[yellow]Tip:[/yellow] use `pal agent create|list|remove|ask`")
    return 0

def parse_llm_spec(spec: str):
    if not spec or ":" not in spec:
        raise ValueError('Invalid spec. Expected "provider:model".')
    provider, model = spec.split(":", 1)
    provider, model = provider.strip(), model.strip()
    if not provider or not model:
        raise ValueError('Invalid spec. Expected "provider:model".')
    return provider, model
