# Research Notes: Leading AI Agent Projects

## 1. Microsoft Magentic-One
- **Architecture**: Lead Orchestrator + 4 specialized agents (WebSurfer, FileSurfer, Coder, ComputerTerminal)
- **Key Innovation**: Dual-loop system
  - Outer Loop: Task Ledger (facts, guesses, plan) — replanning when stuck
  - Inner Loop: Progress Ledger (current progress, task assignment)
- **Agents**: WebSurfer (browser via accessibility tree + set-of-marks), FileSurfer (markdown file preview), Coder (code writing/analysis), ComputerTerminal (shell access)
- **Model-agnostic**: Different LLMs for different agents (e.g., o1-preview for Orchestrator, GPT-4o for others)
- **Error Recovery**: Orchestrator detects stalls via Progress Ledger, triggers replanning via Task Ledger update
- **Multimodal**: WebSurfer uses accessibility tree + visual set-of-marks prompting

## Key differences from Agent-Nimi:
- Agent-Nimi has no WebSurfer/browser agent
- Agent-Nimi's Progress Ledger exists but is simpler
- Agent-Nimi lacks Task Ledger (outer loop replanning)
- Agent-Nimi has no FileSurfer equivalent (file_read tool is simpler)
- Agent-Nimi lacks multimodal/vision capabilities

## 2. PentAGI (vxcontrol) — 14.1k stars
- **Stack**: Go backend, React frontend, PostgreSQL+pgvector, Neo4j, Docker sandboxing
- **Agent Roles**: Assistant, Primary, Pentester, Coder, Installer, Searcher, Enricher, Memorist, Generator, Reporter, Adviser, Reflector, Planner (13+ agents)
- **Execution Monitoring**: Detects identical tool calls (threshold: 5), total tool calls (threshold: 10), auto-invokes "Adviser/Mentor" agent
- **Task Planning**: Planner generates 3-7 steps, wraps in <task_assignment> with instructions
- **Knowledge Graph**: Graphiti + Neo4j for semantic relationship tracking
- **Memory**: Long-term, working, episodic, structured KB, chain summarization for context management
- **Sandboxing**: Docker containers per task, isolated execution
- **Browser**: Built-in web scraper for data gathering
- **Search**: Tavily, Traversaal, Perplexity, DuckDuckGo, Google, Sploitus, Searxng
- **Monitoring**: OpenTelemetry, Grafana, VictoriaMetrics, Jaeger, Loki, Langfuse
- **Tool Limits**: Hard limits (100 for general agents, 20 for limited agents), graceful recovery via Reflector
- **20+ security tools**: nmap, metasploit, sqlmap, etc.

### Key differences from Agent-Nimi:
- PentAGI has 13+ specialized agents vs Agent-Nimi's 5
- PentAGI has Knowledge Graph (Neo4j) vs Agent-Nimi's flat dict world_state
- PentAGI has Docker sandboxing vs Agent-Nimi's direct Kali execution
- PentAGI has built-in browser + 7 search engine integrations
- PentAGI has observability stack (Grafana, Jaeger, etc.)
- PentAGI has chain summarization for context management
- PentAGI has Adviser/Mentor agent for automatic intervention

## 3. MAPTA (Multi-Agent Penetration Testing AI for the Web)
- **Architecture**: 3 agent roles — Coordinator (strategic), Sandbox agents (tactical execution), Validation agent (PoE oracle)
- **Key Innovation**: Mandatory Proof-of-Exploit (PoE) validation for ALL findings — eliminates false positives
- **Performance**: 76.9% on XBOW benchmark (104 challenges), perfect on SSRF/misconfig, 83% SQLi, 85% SSTI
- **Cost**: $21.38 total across 104 challenges, median $0.073 per successful attempt
- **Early-stopping**: ~40 tool calls or $0.30 per challenge threshold
- **Sandboxing**: Shared per-job Docker container for isolated execution
- **Tools**: nmap, python, ffuf integrated via orchestration
- **Real-world**: Found RCEs, command injections, secret exposure in repos with 8K-70K stars; 10 CVEs under review
- **Cost tracking**: Token-level I/O accounting (input, cached, output, reasoning tokens)

## 4. Devin (Cognition)
- Cloud-based autonomous coding agent
- Devin Wiki: auto-indexes repos, generates architecture docs
- Interactive Planning: user can steer mid-execution
- Parallel cloud agents for team workflows
- Full IDE + browser + terminal in cloud sandbox

## 5. CrewAI
- Role-based agent architecture with defined expertise
- Process types: Sequential, Hierarchical, Consensual
- Built-in tool integrations (Gmail, Slack, HubSpot, etc.)
- Memory: Short-term, Long-term, Entity memory
- Delegation between agents
- No-code Studio + full-code SDK

## 6. LangGraph
- Graph-based orchestration: nodes = agents/functions, edges = transitions
- Typed state management across graph
- Conditional edges for dynamic routing
- Built-in persistence and checkpointing
- Human-in-the-loop at any node
- Streaming support for real-time feedback

## 7. AWS Security Agent
- Multi-agent architecture: SAST + DAST + penetration testing combined
- Multicloud support
- Verified security risk reporting (not just theoretical)
- On-demand penetration testing customized per application
