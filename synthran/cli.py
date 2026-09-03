from __future__ import annotations
import argparse, json

def parser():
    root = argparse.ArgumentParser(prog="synthran"); commands = root.add_subparsers(dest="area", required=True)
    model = commands.add_parser("model").add_subparsers(dest="command", required=True); run = model.add_parser("run"); run.add_argument("--config", required=True); run.add_argument("--output", required=True)
    workload = commands.add_parser("workload").add_subparsers(dest="command", required=True); rep = workload.add_parser("replay"); rep.add_argument("--trace", required=True); rep.add_argument("--broker", required=True); rep.add_argument("--port", type=int, default=1883); rep.add_argument("--qos", type=int, default=1); rep.add_argument("--interface"); rep.add_argument("--bind-address"); rep.add_argument("--start-utc"); rep.add_argument("--device"); rep.add_argument("--output", default="publisher.jsonl")
    col = workload.add_parser("collect"); col.add_argument("--broker", default="127.0.0.1"); col.add_argument("--port", type=int, default=1883); col.add_argument("--topic", default="synthran/#"); col.add_argument("--output", default="broker.jsonl")
    results = commands.add_parser("results").add_subparsers(dest="command", required=True); rec = results.add_parser("reconcile"); rec.add_argument("--expected", required=True); rec.add_argument("--publisher", required=True); rec.add_argument("--broker", required=True); rec.add_argument("--output", default="summary.json")
    return root

def main(argv=None):
    args = parser().parse_args(argv)
    if (args.area, args.command) == ("model", "run"):
        from .workload.trace import generate

        print(generate(args.config, args.output))
    elif (args.area, args.command) == ("workload", "replay"):
        from .workload.replay import replay

        replay(args.trace, args.broker, args.port, args.qos, args.interface, args.start_utc, args.output, args.device, args.bind_address)
    elif (args.area, args.command) == ("workload", "collect"):
        from .workload.replay import collect

        collect(args.broker, args.topic, args.port, args.output)
    else:
        from .results import reconcile

        print(json.dumps(reconcile(args.expected, args.publisher, args.broker, args.output), indent=2))

if __name__ == "__main__": main()
