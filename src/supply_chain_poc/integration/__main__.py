import argparse
import json
import logging
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from supply_chain_poc.integration.environment import load_google_key, public_error

from supply_chain_poc.agents import AGENT_CLASSES
from supply_chain_poc.config import ShellSettings
from supply_chain_poc.integration.assembly import assemble_agents
from supply_chain_poc.models import AgentContext


def print_output(output, output_format: str) -> None:
    if output_format == 'table' and isinstance(output, dict) and 'thread_id' in output:
        from supply_chain_poc.integration.comparison_view import render_case
        print(render_case(output))
    else:
        print(json.dumps(output, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description='Preview a role or run the disruption case.')
    parser.add_argument('--role', choices=['all', *AGENT_CLASSES], default='all')
    parser.add_argument('--config', type=Path, default=Path('config/agents.toml'))
    parser.add_argument('--context', type=Path, default=Path('examples/case_context.json'))
    parser.add_argument('--task', default='Assess the delayed shipment in this case and explain supported choices and consequences.')
    parser.add_argument('--run', action='store_true', help='Make live Gemini calls; default is an offline preview.')
    parser.add_argument('--setup-incidents', action='store_true', help='Add the incident table and synthetic fixture; preserve existing rows.')
    parser.add_argument('--compare', action='store_true', help='Calculate choices using SQLite and the local API, without an LLM.')
    parser.add_argument('--format', choices=['json', 'table'], default='json', help='Output format for comparisons or workflow cases.')
    parser.add_argument('--thread-id', help='Persistent workflow identity for start, status and decision commands.')
    parser.add_argument('--status', action='store_true', help='Read an existing workflow case without calling Gemini.')
    parser.add_argument('--decision-file', type=Path, help='Resume a pending case with your human decision JSON.')
    parser.add_argument('--smoke-test', action='store_true', help='One small structured Gemini connectivity test; no business tools.')
    args = parser.parse_args()
    try:
        settings = ShellSettings.load(args.config)
        if args.smoke_test:
            settings = replace(settings, max_model_calls=1, model=replace(settings.model, max_output_tokens=1024))
        if sum((args.run, args.compare, args.setup_incidents, args.status, bool(args.decision_file), args.smoke_test)) > 1:
            raise ValueError('Choose one operation: run, compare, setup, status, decision or smoke test')
        if args.setup_incidents:
            from supply_chain_poc.database.incident_migration import setup_incidents
            print(json.dumps(setup_incidents(settings.database_path, settings.incident_fixture_path), indent=2))
            return
        if args.run or args.decision_file or args.smoke_test:
            load_google_key(settings.dotenv_path)
        agents = assemble_agents(settings)
        if args.status or args.decision_file:
            if not args.thread_id or args.role != 'all':
                raise ValueError('Status and decision commands need --thread-id and the all-role workflow')
            from supply_chain_poc.integration.runner import WorkflowRunner
            runner = WorkflowRunner(settings, agents)
            output = runner.resume(args.thread_id, json.loads(args.decision_file.read_text())) if args.decision_file else runner.status(args.thread_id)
            print_output(output, args.format)
            return
        if args.smoke_test:
            request = agents['inventory'].prepare(
                "Connectivity test only. Return needs_information with summary 'Gemini connectivity verified' and a missing-data question. No factory evidence is supplied.", AgentContext('GEMINI-SMOKE'))
            output = asdict(agents['inventory'].runtime.invoke(request, []))
            print(json.dumps(output, indent=2))
            return
        context = AgentContext(**json.loads(args.context.read_text()))
        if args.compare:
            facts = context.facts
            output = agents['procurement'].tools['compare_options'](
                facts['material_id'], facts['shipment_id'], facts['start_date'], facts.get('days', 5))
            if args.format == 'table':
                from supply_chain_poc.integration.comparison_view import render_comparison
                print(render_comparison(output))
                return
        elif not args.run:
            chosen = agents.values() if args.role == 'all' else [agents[args.role]]
            output = [asdict(agent.prepare(args.task, context)) for agent in chosen]
        else:
            logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
            logging.getLogger('httpx').setLevel(logging.WARNING)
            logging.getLogger('google').setLevel(logging.WARNING)
            if args.role == 'all':
                from supply_chain_poc.integration.runner import WorkflowRunner
                thread_id = args.thread_id or f'{context.case_id}-{uuid4().hex[:8]}'
                output = WorkflowRunner(settings, agents).start(thread_id, args.task, context)
            else:
                output = asdict(agents[args.role].run(args.task, context))
        print_output(output, args.format)
    except Exception as error:
        parser.exit(1, public_error(error) + '\n')


if __name__ == '__main__':
    main()
