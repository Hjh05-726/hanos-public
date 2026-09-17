# Invocation examples

HanOS is adaptive. The model reads the user's content and decides whether the
knowledge workflow is useful. The configured display name and a client command
such as `$hanos` or `/hanos` remain explicit ways to force that workflow, but
they are not required for ordinary capture.

## First-use conversation

| User message | Expected behavior |
|---|---|
| `开始我的知识库。` | Validate the local installation, read relevant setup progress, and ask only the next unknown question in the onboarding flow. |
| `继续上次的引导。` | Resume from the existing global authority without repeating answered or explicitly skipped questions. |
| `先用起来吧，帮我记下今天学到的方法……` | Defer unfinished setup, respond to and capture the real material under the ordinary write rules; do not demand a completed profile. |
| `这段只聊不记。` | Respond without copying the excluded content into a note, profile, or setup-progress summary. |

Do not restart onboarding merely because an older knowledge home has no marker.

## Automatic judgment

| User message | Expected behavior |
|---|---|
| `我发现自己每次做发布前都会跳过回滚演练。` | Recognize a recurring pattern; explain it plainly and, when the source and meaning are clear and low-risk, capture a small feeling or method candidate. |
| `以后我更看重可复现的证据。` | Recognize a stable preference and capture it in the appropriate existing authority. |
| `这周项目的本地测试已经通过，线上状态还没有验证。` | Recognize project state; preserve the distinction between confirmed local evidence and unverified production state. |
| `今天发生了……我很失落，但我不知道为什么。` | Use the cyber-diary experience layer: reflect in simple Chinese, identify possible patterns without diagnosis, and keep highly private material as a candidate until persistence is clearly welcome. |
| `帮我把这个函数改成异步。` | Treat as an ordinary one-off task unless the message also contains durable knowledge; do not scan the knowledge home merely because HanOS exists. |

## Explicit override

| User message | Expected behavior |
|---|---|
| `$hanos 读取 Orbit Garden 的当前状态。` | Force the knowledge workflow, then read only the relevant scope. |
| `/hanos 记录本地调度回归已经通过。` | Force the workflow; apply the core's write protocol and sensitivity checks. |
| `Atlas, 看看我最近为什么总在发布前焦虑。` | Treat the display name as a direct address and use the cyber-diary experience layer. |

## Boundaries

- Automatic capture is limited to small, durable, low-risk items whose source,
  owner, and meaning are clear.
- A temporary complaint, complete chat transcript, secret, third-party
  private detail, or unverified psychological explanation stays out of the
  knowledge base.
- Highly sensitive feelings, health, legal, financial, relationship, delete,
  archive, move, external-project, cloud, and production changes require the
  confirmation rules in the core and write protocol.
- If the authority or destination is ambiguous, stop before writing and ask a
  single scope question. Do not create a second knowledge home.
