import json

from core.parse_args import parse_args
from core.runner import JellyRunner


def main():
    args = parse_args()
    runner = JellyRunner(args)

    results = runner.run_gui() if args.gui else runner.run()
    results["config"] = {
        "seed": args.seed,
        "players": args.players,
        "days": args.days,
        "memory_bytes": args.memory,
        "lifetime_years": args.lifetime_years,
        "initial_jellyfish": args.initial_jellyfish,
        "max_population": args.max_population,
    }

    if args.json_only:
        print(json.dumps(results, indent=2))
        return

    print("RESULTS")
    print("#" * 72)
    print(
        f"{'group':<14}{'final':>7}{'peak':>7}{'births':>8}{'eaten':>7}"
        f"{'old':>6}{'10J day':>9}{'100J day':>10}{'time(s)':>9}"
    )
    for name, r in results["groups"].items():

        def fmt(v):
            return "-" if v is None else str(v)

        print(
            f"{name:<14}{r['final_population']:>7}{r['peak_population']:>7}"
            f"{r['births']:>8}{r['deaths_predator']:>7}{r['deaths_age']:>6}"
            f"{fmt(r['day_reached_10J']):>9}{fmt(r['day_reached_100J']):>10}"
            f"{r['time_used_s']:>9.3f}"
        )
        if r["error"]:
            print(f"   !! crashed: {r['error']}")
    print("#" * 72)


if __name__ == "__main__":
    main()
