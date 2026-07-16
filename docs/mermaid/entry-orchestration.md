# Entry Orchestration Graph

```mermaid
flowchart TD
    START([start]) --> ENTRY[entry_graph]
    ENTRY -->|ready| EXEC[executive_graph]
    ENTRY -->|terminal intake| FINAL[finalize_entry_result]
    EXEC --> FINAL
    FINAL --> END([end])
```

## entry_graph

```mermaid
flowchart TD
    A[normalize_entry] --> B[analyze_task]
    B -->|clarification| C[prepare_clarify_entry]
    C --> D[interrupt_clarify_entry]
    D --> B
    B -->|ready| E([return to parent])
```

## executive_graph

```mermaid
flowchart TD
    A[compile_goal_graph] --> B[project_planning_facts]
    B --> C[assess_coordination]
    C --> D[create_or_revise_plan]
    D --> E[project_control_state]
    E --> F[decide / ControlProposal]
    F --> G[admit_decision]
    G -->|denied| H[handle_decision_denial]
    G -->|accepted| I[admit_execution_route]
    I --> J[apply_decision]
    J -->|action| K[resolve_action]
    K -->|capability gap| E
    K -->|grant| L[action_execution]
    L --> M[observe_action]
    M -->|retry| K
    M -->|verify| N[verify_goal_progress]
    N --> O[monitor_plan]
    O --> B
    J -->|completion| P[verify_completion]
    P -->|continue| B
    P -->|complete| Q([return to parent])
    J -->|loop| B
    H --> Q
```

## action_execution

```mermaid
flowchart TD
    A[prepare_action] --> B[select_action_step]
    B --> C[execute_action_step]
    C -->|native tool| D[action_tool_node]
    D --> E[consume_action_tool_result]
    C -->|ReAct| F[react_action]
    C -->|confirmation| G[confirm_action_step]
    G --> C
    C -->|success| H[handle_action_success]
    C -->|failure| I[recover_action]
    E --> H
    F --> H
    H --> B
    I --> B
```

该图只表达节点与条件边。Admission、Grant、Journal/outbox、Evidence 与 Verification 的业务边界见 [当前核心架构](../summary/core-architecture-current-state.md)。
