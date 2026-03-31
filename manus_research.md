# Manus AI Research Notes

## Architecture
- Multi-agent: Planner Agent + Execution Agent + Verification Agent
- Transformer-based LLM core with multi-modal capabilities
- Context engineering approach (not fine-tuned; in-context learning)
- Rebuilt framework 4 times for optimal context shaping

## Sandbox
- Fully isolated cloud VM per task (via E2B)
- Full OS: networking, file system, browser, software tools
- Zero Trust security model
- Lifecycle: Create → Sleep/Awake → Recycle/Recreate
- Persistence: 7 days (free), 21 days (Pro)
- 24/7 execution without consuming local resources

## Context Engineering (Key Innovations)
- KV-cache optimization: stable prompt prefix, append-only context, explicit cache breakpoints
- Tool masking via logit constraints (not removal) — state machine for tool availability
- File system as extended context (offload data to files, read back on demand)
- Deterministic serialization to preserve cache hits
- Constrained decoding: Auto/Required/Specified function calling modes

## Browser & Vision
- Full Chromium browser in sandbox
- Can browse, fill forms, interact with web apps
- Screenshot-based visual understanding
- "My Browser" feature: uses user's local browser with existing sessions

## Tools & Capabilities
- Shell/terminal execution
- Code writing and execution (Python, Node.js, etc.)
- Web development (full-stack deployment)
- Data analysis and visualization
- File management
- Web browsing and search
- Slides generation
- Image/video/audio generation
- Parallel subtask processing (map)
- Scheduled tasks (cron/interval)
- MCP server integration
- Agent Skills (modular capability extensions)

## Memory & State
- File system as persistent memory
- Context window management with compression
- Append-only message history
- Todo.md files for task tracking
- No explicit knowledge graph

## Self-Correction
- Verification Agent reviews all outputs
- Can trigger re-planning if results fail verification
- Reflexion-like retry on quality issues

## Observability
- Real-time SSE streaming of agent actions
- Sandbox status visible to user
- Reasoning traces visible in UI

## Human-in-the-Loop
- User can steer mid-execution
- Collaboration mode (multi-user)
- Confirmation gates for sensitive operations
- Browser takeover for login/personal info

## Search Integration
- Built-in web search tool
- Deep research mode ("Wide Research")
- Multiple search types: info, image, api, news, tool, data, research

## Cost & Budget
- Subscription-based (not per-token)
- No explicit per-task cost tracking exposed to user

## Scale
- $100M ARR in 8 months
- Acquired by Meta in 2026
- GAIA benchmark leader
