# Ask 当前依赖图

```mermaid
flowchart LR
    Question["Question + visible conversation hints"]
    Understanding["Query understanding"]

    subgraph Retrieval["Retrieval Stage"]
        Workspace["Workspace evidence selection"]
        Local["Local note/chunk retrieval"]
        Graph["Graphiti / structural retrieval"]
        Web["Policy-governed web retrieval"]
        Normalize["Canonical EvidenceItem conversion"]
        Evidence["Shared evidence pool"]
    end

    Engine["Evidence Engine<br/>dedupe / fusion / rerank / budget"]
    ContextPack["ContextPack"]
    Compose["Unified answer compose"]
    Verify["Ask Verifier"]
    Repair["Bounded repair"]
    Result["AskResult"]

    Question --> Understanding
    Understanding --> Workspace
    Understanding --> Local
    Understanding --> Graph
    Understanding --> Web
    Workspace --> Normalize
    Local --> Normalize
    Graph --> Normalize
    Web --> Normalize
    Normalize --> Evidence
    Evidence --> Engine
    Engine --> ContextPack
    ContextPack --> Compose
    Compose --> Verify
    Verify -->|passed or explicit insufficiency| Result
    Verify -->|repairable gap| Repair
    Repair --> Verify
```

Workspace 和 Graph 在该路径只返回 evidence。它们不生成内部候选答案，不运行自己的 Completion，
也不把 Provider answer 投影成 fact。独立 Workspace Answer 产品入口的验证边界见
[Verification 与 Completion](../topics/verification-and-completion.md)。
