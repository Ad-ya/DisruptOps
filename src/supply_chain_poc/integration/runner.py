from dataclasses import asdict
from datetime import datetime

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from supply_chain_poc.config import ShellSettings
from supply_chain_poc.integration.nodes import WORKFLOW_VERSION, utc_now
from supply_chain_poc.integration.workflow import build_workflow
from supply_chain_poc.models import AgentContext
from supply_chain_poc.schemas.decision import validate_human_decision


class WorkflowRunner:
    def __init__(self, settings: ShellSettings, agents: dict, clock=utc_now) -> None:
        if settings.checkpoint_path == settings.database_path:
            raise ValueError('Checkpoint storage must be separate from the factory database')
        self.settings, self.agents, self.clock = settings, agents, clock

    def _config(self, thread_id: str) -> dict:
        if not thread_id.strip():
            raise ValueError('A nonempty thread_id is required')
        return {'configurable': {'thread_id': thread_id},
                'recursion_limit': max(60, self.settings.max_graph_steps * (self.settings.workflow.max_revisions + 2))}

    def _open(self):
        self.settings.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        return SqliteSaver.from_conn_string(str(self.settings.checkpoint_path))

    def _graph(self, checkpointer):
        return build_workflow(self.agents, settings=self.settings.workflow,
                              checkpointer=checkpointer, clock=self.clock)

    def start(self, thread_id: str, task: str, context: AgentContext) -> dict:
        config = self._config(thread_id)
        if not task.strip() or not context.case_id.strip():
            raise ValueError('A task and case_id are required')
        with self._open() as checkpointer:
            graph = self._graph(checkpointer)
            if graph.get_state(config).values:
                raise ValueError('Thread already exists; inspect or resume it, or choose a new thread_id')
            graph.invoke({'task': task, 'context': asdict(context), 'results': {}}, config)
            return self._view(thread_id, graph.get_state(config).values)

    def status(self, thread_id: str) -> dict:
        config = self._config(thread_id)
        with self._open() as checkpointer:
            return self._view(thread_id, self._graph(checkpointer).get_state(config).values)

    def resume(self, thread_id: str, value: dict) -> dict:
        config = self._config(thread_id)
        with self._open() as checkpointer:
            graph = self._graph(checkpointer)
            state = graph.get_state(config).values
            if not state:
                raise ValueError('Unknown workflow thread')
            if state.get('workflow_version') != WORKFLOW_VERSION:
                raise ValueError('This case uses the older workflow; start a new thread ID for parallel assessment')
            decision = validate_human_decision(value, state)
            graph.invoke(Command(resume=decision.model_dump(mode='json')), config)
            return self._view(thread_id, graph.get_state(config).values)

    def _view(self, thread_id: str, state: dict) -> dict:
        if not state:
            raise ValueError('Unknown workflow thread')
        output = {'workflow_version': state.get('workflow_version', 1), 'thread_id': thread_id, 'case_id': state['context']['case_id'],
                  'status': state['status'], 'revision_count': state['revision_count'],
                  'comparison_version': state['comparison_version'], 'reason': state.get('reason', ''),
                  'findings': state['results'], 'comparison': state.get('comparison'),
                  'decision': state.get('decision'), 'events': state.get('events', [])}
        if state['status'] == 'awaiting_approval':
            expires = datetime.fromisoformat(state['approval_expires_at'])
            output['approval_expires_at'] = expires.isoformat()
            output['approval_is_expired'] = self.clock() >= expires
            output['decision_template'] = {
                'action': 'approve', 'reviewer_id': 'your-name', 'case_id': output['case_id'],
                'thread_id': thread_id, 'snapshot_id': state['comparison']['snapshot_id'],
                'comparison_version': state['comparison_version'],
                'option_id': state['comparison']['recommended_option_id'],
                'acknowledge_consequences': True, 'comment': ''}
            output['decision_instructions'] = 'Review every scenario, edit the template, save it as JSON, and pass --decision-file. Nothing is approved automatically.'
        return output
