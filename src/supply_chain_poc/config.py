from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

MIDDLEWARE_NAMES = frozenset({'audit', 'model_call_limit'})


@dataclass(frozen=True, slots=True)
class ModelSettings:
    name: str
    temperature: float
    max_output_tokens: int
    thinking_level: str | None = None
    timeout_seconds: int = 60


@dataclass(frozen=True, slots=True)
class ComparisonSettings:
    stress_demand_percent: int = 120
    replacement_delay_days: int = 1


@dataclass(frozen=True, slots=True)
class WorkflowSettings:
    max_revisions: int = 1
    approval_ttl_minutes: int = 60


@dataclass(frozen=True, slots=True)
class RoleSettings:
    instructions: str
    skills: tuple[str, ...]
    tools: tuple[str, ...]
    middleware: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShellSettings:
    model: ModelSettings
    shared_instructions: str
    skills: dict[str, str]
    roles: dict[str, RoleSettings]
    max_model_calls: int
    max_graph_steps: int
    database_path: Path
    supplier_api_url: str
    supplier_api_timeout: float
    incident_fixture_path: Path
    comparison: ComparisonSettings
    workflow: WorkflowSettings
    checkpoint_path: Path
    dotenv_path: Path

    @classmethod
    def load(cls, path: Path) -> ShellSettings:
        with path.open('rb') as file:
            raw = tomllib.load(file)
        model = ModelSettings(**raw['model'])
        defaults = raw['defaults']
        roles = {}
        for name, values in raw['agents'].items():
            role = RoleSettings(
                instructions=values['instructions'],
                skills=tuple(values.get('skills', [])),
                tools=tuple(values.get('tools', [])),
                middleware=tuple(values.get('middleware', defaults['middleware'])),
            )
            if not role.instructions.strip():
                raise ValueError(f'{name}: role instructions cannot be empty')
            unknown_skills = set(role.skills) - raw['skills'].keys()
            unknown_middleware = set(role.middleware) - MIDDLEWARE_NAMES
            if unknown_skills or unknown_middleware:
                raise ValueError(f'{name}: unknown skills {unknown_skills} or middleware {unknown_middleware}')
            if len(role.middleware) != len(set(role.middleware)):
                raise ValueError(f'{name}: duplicate middleware')
            roles[name] = role
        for value in (defaults['max_model_calls'], defaults['max_graph_steps'], model.max_output_tokens):
            if type(value) is not int or value <= 0:
                raise ValueError('Call, graph-step and output-token limits must be positive integers')
        if not model.name.strip() or not 0 <= model.temperature <= 2:
            raise ValueError('A model name and temperature between 0 and 2 are required')
        if model.thinking_level not in {None, 'minimal', 'low', 'medium', 'high'} or model.timeout_seconds <= 0:
            raise ValueError('Invalid model thinking level or timeout')
        if not raw['shared']['instructions'].strip() or any(not p.strip() for p in raw['skills'].values()):
            raise ValueError('Shared instructions and skill prompts cannot be empty')
        comparison = ComparisonSettings(**raw.get('comparison', {}))
        workflow_values = dict(raw.get('workflow', {}))
        checkpoint = workflow_values.pop('checkpoint_path', '../data/workflow.sqlite')
        workflow = WorkflowSettings(**workflow_values)
        if (type(workflow.max_revisions) is not int or not 0 <= workflow.max_revisions <= 5
                or type(workflow.approval_ttl_minutes) is not int or workflow.approval_ttl_minutes <= 0):
            raise ValueError('Workflow needs 0-5 revisions and a positive approval lifetime')
        if (type(comparison.stress_demand_percent) is not int or comparison.stress_demand_percent < 100
                or type(comparison.replacement_delay_days) is not int or comparison.replacement_delay_days < 0):
            raise ValueError('Stress demand must be >=100 percent; additional delay must be nonnegative')
        return cls(model, raw['shared']['instructions'], raw['skills'], roles,
                   defaults['max_model_calls'], defaults['max_graph_steps'],
                   (path.resolve().parent / raw['database']['path']).resolve(),
                   raw['supplier_api']['base_url'], raw['supplier_api']['timeout_seconds'],
                   (path.resolve().parent / raw['database']['incident_fixture']).resolve(), comparison, workflow,
                   (path.resolve().parent / checkpoint).resolve(),
                   (path.resolve().parent / raw.get('environment', {}).get('dotenv_path', '../.env')).resolve())
