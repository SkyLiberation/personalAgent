# Entry Orchestration Graph (Top Level)
```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	entry_graph(entry_graph)
	executive_graph(executive_graph)
	finalize_entry_result(finalize_entry_result)
	__end__([<p>__end__</p>]):::last
	__start__ --> entry_graph;
	entry_graph -. &nbsp;executive&nbsp; .-> executive_graph;
	entry_graph -. &nbsp;finalize&nbsp; .-> finalize_entry_result;
	executive_graph --> finalize_entry_result;
	finalize_entry_result --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

```

## Subgraph: entry_graph
```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	normalize_entry(normalize_entry)
	analyze_task(analyze_task)
	prepare_clarify_entry(prepare_clarify_entry)
	interrupt_clarify_entry(interrupt_clarify_entry)
	__end__([<p>__end__</p>]):::last
	__start__ --> normalize_entry;
	analyze_task -. &nbsp;return_to_parent&nbsp; .-> __end__;
	analyze_task -.-> prepare_clarify_entry;
	interrupt_clarify_entry -. &nbsp;finalize_entry_result&nbsp; .-> __end__;
	interrupt_clarify_entry -.-> analyze_task;
	normalize_entry --> analyze_task;
	prepare_clarify_entry -.-> analyze_task;
	prepare_clarify_entry -.-> interrupt_clarify_entry;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

```

## Subgraph: executive_graph
```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	compile_goal_graph(compile_goal_graph)
	project_control_state(project_control_state)
	decide(decide)
	validate_decision(validate_decision)
	apply_decision(apply_decision)
	action_execution(action_execution)
	observe_action(observe_action)
	verify_goal_progress(verify_goal_progress)
	verify_completion(verify_completion)
	__end__([<p>__end__</p>]):::last
	__start__ --> compile_goal_graph;
	action_execution --> observe_action;
	apply_decision -. &nbsp;stop&nbsp; .-> __end__;
	apply_decision -. &nbsp;action&nbsp; .-> action_execution;
	apply_decision -. &nbsp;loop&nbsp; .-> project_control_state;
	apply_decision -. &nbsp;completion&nbsp; .-> verify_completion;
	compile_goal_graph --> project_control_state;
	decide --> validate_decision;
	observe_action --> verify_goal_progress;
	project_control_state --> decide;
	validate_decision --> apply_decision;
	verify_completion -. &nbsp;complete&nbsp; .-> __end__;
	verify_completion -. &nbsp;loop&nbsp; .-> project_control_state;
	verify_goal_progress --> project_control_state;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

```

## Subgraph: action_execution
```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	prepare_action(prepare_action)
	select_action_step(select_action_step)
	execute_action_step(execute_action_step)
	handle_action_success(handle_action_success)
	recover_action(recover_action)
	confirm_action_step(confirm_action_step)
	action_tool_node(action_tool_node)
	consume_action_tool_result(consume_action_tool_result)
	react_action(react_action)
	__end__([<p>__end__</p>]):::last
	__start__ --> prepare_action;
	action_tool_node --> consume_action_tool_result;
	confirm_action_step -. &nbsp;tool_node&nbsp; .-> action_tool_node;
	confirm_action_step -. &nbsp;handle_success&nbsp; .-> handle_action_success;
	confirm_action_step -. &nbsp;handle_failure&nbsp; .-> recover_action;
	consume_action_tool_result -. &nbsp;tool_node&nbsp; .-> action_tool_node;
	consume_action_tool_result -. &nbsp;confirm_step&nbsp; .-> confirm_action_step;
	consume_action_tool_result -. &nbsp;handle_success&nbsp; .-> handle_action_success;
	consume_action_tool_result -. &nbsp;react_step&nbsp; .-> react_action;
	consume_action_tool_result -. &nbsp;handle_failure&nbsp; .-> recover_action;
	execute_action_step -. &nbsp;tool_node&nbsp; .-> action_tool_node;
	execute_action_step -. &nbsp;confirm_step&nbsp; .-> confirm_action_step;
	execute_action_step -. &nbsp;handle_success&nbsp; .-> handle_action_success;
	execute_action_step -. &nbsp;react_step&nbsp; .-> react_action;
	execute_action_step -. &nbsp;handle_failure&nbsp; .-> recover_action;
	handle_action_success --> select_action_step;
	prepare_action --> select_action_step;
	react_action -. &nbsp;handle_success&nbsp; .-> handle_action_success;
	react_action -. &nbsp;recover&nbsp; .-> recover_action;
	recover_action -. &nbsp;action_done&nbsp; .-> __end__;
	recover_action -. &nbsp;retry&nbsp; .-> select_action_step;
	select_action_step -. &nbsp;finalize_steps&nbsp; .-> __end__;
	select_action_step -. &nbsp;execute_step&nbsp; .-> execute_action_step;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

```

## Subgraph: react_action
```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	react_init(react_init)
	react_iterate(react_iterate)
	react_tool_node(react_tool_node)
	consume_react_tool_result(consume_react_tool_result)
	react_finalize(react_finalize)
	__end__([<p>__end__</p>]):::last
	__start__ --> react_init;
	consume_react_tool_result -. &nbsp;finalize&nbsp; .-> react_finalize;
	consume_react_tool_result -. &nbsp;iterate&nbsp; .-> react_iterate;
	consume_react_tool_result -. &nbsp;tool_node&nbsp; .-> react_tool_node;
	react_init --> react_iterate;
	react_iterate -. &nbsp;finalize&nbsp; .-> react_finalize;
	react_iterate -. &nbsp;tool_node&nbsp; .-> react_tool_node;
	react_tool_node --> consume_react_tool_result;
	react_finalize --> __end__;
	react_iterate -. &nbsp;iterate&nbsp; .-> react_iterate;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

```

# Entry Orchestration Graph (X-Ray depth=2)
```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	finalize_entry_result(finalize_entry_result)
	__end__([<p>__end__</p>]):::last
	__start__ --> entry_graph\3anormalize_entry;
	entry_graph\3a__end__ -. &nbsp;executive&nbsp; .-> executive_graph\3acompile_goal_graph;
	entry_graph\3a__end__ -. &nbsp;finalize&nbsp; .-> finalize_entry_result;
	executive_graph\3a__end__ --> finalize_entry_result;
	finalize_entry_result --> __end__;
	subgraph entry_graph
	entry_graph\3anormalize_entry(normalize_entry)
	entry_graph\3aanalyze_task(analyze_task)
	entry_graph\3aprepare_clarify_entry(prepare_clarify_entry)
	entry_graph\3ainterrupt_clarify_entry(interrupt_clarify_entry)
	entry_graph\3a__end__(<p>__end__</p>)
	entry_graph\3aanalyze_task -. &nbsp;return_to_parent&nbsp; .-> entry_graph\3a__end__;
	entry_graph\3aanalyze_task -.-> entry_graph\3aprepare_clarify_entry;
	entry_graph\3ainterrupt_clarify_entry -. &nbsp;finalize_entry_result&nbsp; .-> entry_graph\3a__end__;
	entry_graph\3ainterrupt_clarify_entry -.-> entry_graph\3aanalyze_task;
	entry_graph\3anormalize_entry --> entry_graph\3aanalyze_task;
	entry_graph\3aprepare_clarify_entry -.-> entry_graph\3aanalyze_task;
	entry_graph\3aprepare_clarify_entry -.-> entry_graph\3ainterrupt_clarify_entry;
	end
	subgraph executive_graph
	executive_graph\3acompile_goal_graph(compile_goal_graph)
	executive_graph\3aproject_control_state(project_control_state)
	executive_graph\3adecide(decide)
	executive_graph\3avalidate_decision(validate_decision)
	executive_graph\3aapply_decision(apply_decision)
	executive_graph\3aobserve_action(observe_action)
	executive_graph\3averify_goal_progress(verify_goal_progress)
	executive_graph\3averify_completion(verify_completion)
	executive_graph\3a__end__(<p>__end__</p>)
	executive_graph\3aaction_execution\3a__end__ --> executive_graph\3aobserve_action;
	executive_graph\3aapply_decision -. &nbsp;stop&nbsp; .-> executive_graph\3a__end__;
	executive_graph\3aapply_decision -. &nbsp;action&nbsp; .-> executive_graph\3aaction_execution\3aprepare_action;
	executive_graph\3aapply_decision -. &nbsp;loop&nbsp; .-> executive_graph\3aproject_control_state;
	executive_graph\3aapply_decision -. &nbsp;completion&nbsp; .-> executive_graph\3averify_completion;
	executive_graph\3acompile_goal_graph --> executive_graph\3aproject_control_state;
	executive_graph\3adecide --> executive_graph\3avalidate_decision;
	executive_graph\3aobserve_action --> executive_graph\3averify_goal_progress;
	executive_graph\3aproject_control_state --> executive_graph\3adecide;
	executive_graph\3avalidate_decision --> executive_graph\3aapply_decision;
	executive_graph\3averify_completion -. &nbsp;complete&nbsp; .-> executive_graph\3a__end__;
	executive_graph\3averify_completion -. &nbsp;loop&nbsp; .-> executive_graph\3aproject_control_state;
	executive_graph\3averify_goal_progress --> executive_graph\3aproject_control_state;
	subgraph action_execution
	executive_graph\3aaction_execution\3aprepare_action(prepare_action)
	executive_graph\3aaction_execution\3aselect_action_step(select_action_step)
	executive_graph\3aaction_execution\3aexecute_action_step(execute_action_step)
	executive_graph\3aaction_execution\3ahandle_action_success(handle_action_success)
	executive_graph\3aaction_execution\3arecover_action(recover_action)
	executive_graph\3aaction_execution\3aconfirm_action_step(confirm_action_step)
	executive_graph\3aaction_execution\3aaction_tool_node(action_tool_node)
	executive_graph\3aaction_execution\3aconsume_action_tool_result(consume_action_tool_result)
	executive_graph\3aaction_execution\3areact_action(react_action)
	executive_graph\3aaction_execution\3a__end__(<p>__end__</p>)
	executive_graph\3aaction_execution\3aaction_tool_node --> executive_graph\3aaction_execution\3aconsume_action_tool_result;
	executive_graph\3aaction_execution\3aconfirm_action_step -. &nbsp;tool_node&nbsp; .-> executive_graph\3aaction_execution\3aaction_tool_node;
	executive_graph\3aaction_execution\3aconfirm_action_step -. &nbsp;handle_success&nbsp; .-> executive_graph\3aaction_execution\3ahandle_action_success;
	executive_graph\3aaction_execution\3aconfirm_action_step -. &nbsp;handle_failure&nbsp; .-> executive_graph\3aaction_execution\3arecover_action;
	executive_graph\3aaction_execution\3aconsume_action_tool_result -. &nbsp;tool_node&nbsp; .-> executive_graph\3aaction_execution\3aaction_tool_node;
	executive_graph\3aaction_execution\3aconsume_action_tool_result -. &nbsp;confirm_step&nbsp; .-> executive_graph\3aaction_execution\3aconfirm_action_step;
	executive_graph\3aaction_execution\3aconsume_action_tool_result -. &nbsp;handle_success&nbsp; .-> executive_graph\3aaction_execution\3ahandle_action_success;
	executive_graph\3aaction_execution\3aconsume_action_tool_result -. &nbsp;react_step&nbsp; .-> executive_graph\3aaction_execution\3areact_action;
	executive_graph\3aaction_execution\3aconsume_action_tool_result -. &nbsp;handle_failure&nbsp; .-> executive_graph\3aaction_execution\3arecover_action;
	executive_graph\3aaction_execution\3aexecute_action_step -. &nbsp;tool_node&nbsp; .-> executive_graph\3aaction_execution\3aaction_tool_node;
	executive_graph\3aaction_execution\3aexecute_action_step -. &nbsp;confirm_step&nbsp; .-> executive_graph\3aaction_execution\3aconfirm_action_step;
	executive_graph\3aaction_execution\3aexecute_action_step -. &nbsp;handle_success&nbsp; .-> executive_graph\3aaction_execution\3ahandle_action_success;
	executive_graph\3aaction_execution\3aexecute_action_step -. &nbsp;react_step&nbsp; .-> executive_graph\3aaction_execution\3areact_action;
	executive_graph\3aaction_execution\3aexecute_action_step -. &nbsp;handle_failure&nbsp; .-> executive_graph\3aaction_execution\3arecover_action;
	executive_graph\3aaction_execution\3ahandle_action_success --> executive_graph\3aaction_execution\3aselect_action_step;
	executive_graph\3aaction_execution\3aprepare_action --> executive_graph\3aaction_execution\3aselect_action_step;
	executive_graph\3aaction_execution\3areact_action -. &nbsp;handle_success&nbsp; .-> executive_graph\3aaction_execution\3ahandle_action_success;
	executive_graph\3aaction_execution\3areact_action -. &nbsp;recover&nbsp; .-> executive_graph\3aaction_execution\3arecover_action;
	executive_graph\3aaction_execution\3arecover_action -. &nbsp;action_done&nbsp; .-> executive_graph\3aaction_execution\3a__end__;
	executive_graph\3aaction_execution\3arecover_action -. &nbsp;retry&nbsp; .-> executive_graph\3aaction_execution\3aselect_action_step;
	executive_graph\3aaction_execution\3aselect_action_step -. &nbsp;finalize_steps&nbsp; .-> executive_graph\3aaction_execution\3a__end__;
	executive_graph\3aaction_execution\3aselect_action_step -. &nbsp;execute_step&nbsp; .-> executive_graph\3aaction_execution\3aexecute_action_step;
	end
	end
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

```
