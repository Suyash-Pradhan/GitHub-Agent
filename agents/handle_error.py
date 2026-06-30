from state import AgentState


def handle_error(state: AgentState) -> AgentState:
    print(f"\n[Orchestrator] Pipeline stopped due to error: {state.get('error')}")
    return state
