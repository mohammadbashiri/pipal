import argparse, sys
from pathlib import Path
from rich import print
from .registry import add_agent, rm_agent, list_agents, get_agent
from .llm_config import load_llm_config
from .agent_scaffold import ensure_agent_scaffold, write_llm_json


def build_parser():
    p = argparse.ArgumentParser(prog="pi", add_help=True)
    sub = p.add_subparsers(dest="cmd")

    pa = sub.add_parser("agent", help="Manage agents")
    sub2 = pa.add_subparsers(dest="agent_cmd")

    p_add = sub2.add_parser("add", help="Register an agent (and create folder if missing)")
    p_add.add_argument("name")
    p_add.add_argument("path", nargs="?", default=None)

    p_rm = sub2.add_parser("rm", help="Remove an agent")
    p_rm.add_argument("name")

    sub2.add_parser("ls", help="List agents")

    p_set = sub2.add_parser("set-llm", help="Set agent llm.json")
    p_set.add_argument("name")
    p_set.add_argument("spec", nargs="?", default=None, help='Either "provider:model" or omit to use flags')
    p_set.add_argument("--provider", default=None)
    p_set.add_argument("--model", default=None)

    return p

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    # Agent mode (passthrough prompt)
    if "--agent" in argv:
        i = argv.index("--agent")
        if i + 1 >= len(argv):
            print("[red]Missing agent name after --agent[/red]")
            return 2
        name = argv[i + 1]
        prompt = " ".join(argv[i + 2:]).strip()

        a = get_agent(name)
        if not a:
            print(f"[red]Unknown agent[/red] {name}. Run: pi agent ls")
            return 2

        llm = load_llm_config(a["path"])
        print(f"[cyan]Agent[/cyan] {a['name']} → {a['path']}")
        if llm:
            print(f"[cyan]LLM[/cyan] provider={llm.get('provider')} model={llm.get('model')} endpoint={llm.get('endpoint')}")
        else:
            print("[yellow]No llm.json found in agent folder[/yellow]")

        if prompt:
            print(f"[cyan]Prompt[/cyan] {prompt}")
        return 0

    args = build_parser().parse_args(argv)

    if args.cmd == "agent":
        if args.agent_cmd == "add":
            path = args.path or f"./{args.name}"
            path = str(Path(path).expanduser().resolve())
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

            ensure_agent_scaffold(path)

            print(f"[dim]Set model with:[/dim]")
            print(f"[dim]pi agent set-llm {args.name} \"provider:model\"[/dim]")


            return 0

        if args.agent_cmd == "rm":
            ok = rm_agent(args.name)
            print("[green]OK[/green] removed" if ok else "[yellow]Not found[/yellow]")
            return 0

        if args.agent_cmd == "ls":
            agents = list_agents()
            if not agents:
                print("[yellow]No agents registered[/yellow]")
                return 0
            for name, p in agents.items():
                print(f"- [bold]{name}[/bold]  {p}")
            return 0
        
        if args.agent_cmd == "set-llm":
            a = get_agent(args.name)
            if not a:
                print(f"[red]Unknown agent[/red] {args.name}. Run: pi agent ls")
                return 2

            ensure_agent_scaffold(a["path"])

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
                print(f'  pi agent set-llm {args.name} --provider ollama --model "Mistral:7b"')
                print(f'  pi agent set-llm {args.name} "ollama:Mistral:7b"')
                return 2

            written = write_llm_json(a["path"], provider, model)
            print(f"[green]Updated[/green] {written}")
            print(f"[cyan]LLM[/cyan] provider={provider} model={model}")
            return 0

    print("[yellow]Tip:[/yellow] use `pi agent add|ls|rm` or `pi --agent <name> \"...\"`")
    return 0

def parse_llm_spec(spec: str):
    if not spec or ":" not in spec:
        raise ValueError('Invalid spec. Expected "provider:model".')
    provider, model = spec.split(":", 1)
    provider, model = provider.strip(), model.strip()
    if not provider or not model:
        raise ValueError('Invalid spec. Expected "provider:model".')
    return provider, model