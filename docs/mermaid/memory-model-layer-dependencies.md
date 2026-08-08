# Memory 事实与投影依赖图

```mermaid
flowchart LR
    User["User / external source"]

    subgraph RuntimeFacts["运行事实 owner"]
        Conversation["Interaction journal<br/>messages / observations / feedback"]
        Project["Investigation journal<br/>definition / plan / step facts"]
        Research["Research store<br/>run / event / delivery"]
        Lifecycle["Knowledge lifecycle store<br/>command / operation / receipt"]
    end

    subgraph KnowledgeFacts["长期知识 owner"]
        Artifact["Artifact Store<br/>large content"]
        Personal Knowledge["Personal Knowledge Store<br/>EvidenceSpan / Claim / Relation"]
    end

    subgraph Projections["可重建检索投影"]
        Embedding["Embedding / search index"]
        Graph["Graphiti<br/>node / edge / episode / fact ref"]
    end

    subgraph Context["单次模型上下文"]
        Visibility["Visibility"]
        Retrieval["Requirement Retrieval"]
        Selection["Semantic Selection"]
        Budget["Budget Materialization"]
        LlmContext["LLM Context"]
    end

    User --> Conversation
    User --> Artifact
    Artifact --> Personal Knowledge
    Personal Knowledge --> Embedding
    Personal Knowledge --> Graph
    Personal Knowledge --> Visibility
    Conversation --> Visibility
    Project --> Visibility
    Research --> Visibility
    Lifecycle --> Visibility
    Visibility --> Retrieval
    Embedding --> Retrieval
    Graph --> Retrieval
    Retrieval --> Selection
    Selection --> Budget
    Budget --> LlmContext
```

检索投影不能反向写入 Personal Knowledge facts；LLM Context 也不能自动写回 Conversation 或长期知识。
完整规则见 [Memory 与知识事实边界](../topics/memory.md)。
