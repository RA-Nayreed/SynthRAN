from __future__ import annotations

import argparse
import json


def parser():
    root = argparse.ArgumentParser(prog="synthran")
    commands = root.add_subparsers(dest="area", required=True)
    model = commands.add_parser("model").add_subparsers(dest="command", required=True)
    run = model.add_parser("run")
    run.add_argument("--config", required=True)
    run.add_argument("--output", required=True)
    workload = commands.add_parser("workload").add_subparsers(
        dest="command", required=True
    )
    replay = workload.add_parser("replay")
    replay.add_argument("--trace", required=True)
    replay.add_argument("--broker", required=True)
    replay.add_argument("--port", type=int, default=1883)
    replay.add_argument("--qos", type=int, choices=(0, 1), default=1)
    replay.add_argument("--interface")
    replay.add_argument("--bind-address")
    replay.add_argument("--start-utc")
    filtering = replay.add_mutually_exclusive_group()
    filtering.add_argument("--device")
    filtering.add_argument("--gateway")
    replay.add_argument("--max-inflight", type=int, default=20)
    replay.add_argument("--max-queued", type=int, default=10000)
    replay.add_argument("--drain-seconds", type=float, default=60)
    replay.add_argument("--horizon-seconds", type=float)
    replay.add_argument("--output", default="publisher.jsonl")
    collect = workload.add_parser("collect")
    collect.add_argument("--broker", default="127.0.0.1")
    collect.add_argument("--port", type=int, default=1883)
    collect.add_argument("--topic", default="synthran/#")
    collect.add_argument("--output", default="broker.jsonl")
    collect.add_argument("--ready-file")
    transform = workload.add_parser("transform")
    transform.add_argument("--source", required=True)
    transform.add_argument("--output", required=True)
    transform.add_argument(
        "--variant", choices=("native", "gap_permutation", "periodic"), required=True
    )
    transform.add_argument("--seed", type=int, default=1)
    transform.add_argument("--warmup-seconds", type=float, default=0)
    import_command = workload.add_parser("import")
    import_command.add_argument("--source", required=True)
    import_command.add_argument("--output", required=True)
    import_command.add_argument("--config", required=True)
    validate = workload.add_parser("validate")
    validate.add_argument("--source", required=True)
    results = commands.add_parser("results").add_subparsers(
        dest="command", required=True
    )
    reconcile = results.add_parser("reconcile")
    reconcile.add_argument("--expected", required=True)
    reconcile.add_argument("--publisher", required=True)
    reconcile.add_argument("--broker", required=True)
    reconcile.add_argument("--scenario")
    reconcile.add_argument("--output", default="summary.json")
    reconcile.add_argument("--require-deployment-identity", action="store_true")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    if (args.area, args.command) == ("model", "run"):
        from .workload.trace import generate

        print(generate(args.config, args.output))
    elif (args.area, args.command) == ("workload", "replay"):
        from .workload.replay import replay

        replay(
            args.trace,
            args.broker,
            args.port,
            args.qos,
            args.interface,
            args.start_utc,
            args.output,
            args.device,
            args.bind_address,
            gateway=args.gateway,
            max_inflight=args.max_inflight,
            max_queued=args.max_queued,
            drain_seconds=args.drain_seconds,
            horizon_seconds=args.horizon_seconds,
        )
    elif (args.area, args.command) == ("workload", "collect"):
        from .workload.replay import collect

        collect(args.broker, args.topic, args.port, args.output, args.ready_file)
    elif (args.area, args.command) == ("workload", "transform"):
        from .workload.bundle import transform_bundle

        print(
            transform_bundle(
                args.source, args.output, args.variant, args.seed, args.warmup_seconds
            )
        )
    elif (args.area, args.command) == ("workload", "import"):
        from .workload.bundle import import_bundle

        print(import_bundle(args.source, args.output, args.config))
    elif (args.area, args.command) == ("workload", "validate"):
        from .workload.bundle import validate_bundle

        print(json.dumps(validate_bundle(args.source), indent=2))
    else:
        from .results import reconcile

        print(
            json.dumps(
                reconcile(
                    args.expected,
                    args.publisher,
                    args.broker,
                    args.output,
                    args.scenario,
                    args.require_deployment_identity,
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
