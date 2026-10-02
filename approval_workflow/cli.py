import argparse
import json
import os

from .workflow import Action, Workflow, plan_live, review_live


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=os.getenv("PORTFOLIO_DB", "approval.db"))
    sub = parser.add_subparsers(dest="command", required=True)
    propose = sub.add_parser("propose")
    propose.add_argument("--request", help="Use the model to create a typed proposal")
    propose.add_argument("--kind", choices=["add_note", "close_incident"])
    propose.add_argument("--incident-id", type=int)
    propose.add_argument("--reason")
    decide = sub.add_parser("decide")
    decide.add_argument("job_id")
    decide.add_argument("--actor", required=True)
    decision = decide.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    show = sub.add_parser("show")
    show.add_argument("job_id")
    args = parser.parse_args()
    if args.command == "propose":
        manual = (args.kind, args.incident_id, args.reason)
        if args.request is not None:
            if not args.request.strip():
                parser.error("--request cannot be blank")
            if any(value is not None for value in manual):
                parser.error("--request cannot be combined with --kind, --incident-id, or --reason")
        elif any(value is None for value in manual):
            parser.error("propose requires --request or all of --kind, --incident-id, and --reason")
    workflow = Workflow(args.db)
    if args.command == "propose":
        action = plan_live(args.request) if args.request else Action(
            kind=args.kind, incident_id=args.incident_id, reason=args.reason)
        review = review_live(action) if args.request else None
        print(workflow.propose(action, review=review))
    elif args.command == "decide":
        print(workflow.decide(args.job_id, args.approve, args.actor))
    else:
        print(json.dumps(workflow.get(args.job_id), indent=2))


if __name__ == "__main__":
    main()
