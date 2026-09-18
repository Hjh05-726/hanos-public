# First-use conversation

Introduce HanOS through five short questions and one real record. Use the
user's language; the Chinese copy below is the default for Chinese conversations.
The questions are a conversation guide, not five required form fields.

## Enter or resume

Resolve the local config, registry, entry note, and write rules before saving.
Setup does not bypass a missing or invalid installation. Explain a missing
prerequisite plainly; do not guess or initialize a replacement knowledge home.

Start when the user asks to begin, set up, or personalize their knowledge base,
or makes a first standalone invocation in a confirmed fresh installation.
Use the entry note and relevant global index to distinguish scaffold-only
content from an established home. Do not scan diaries to fill in a profile.
An established home without an onboarding marker is not a new user.
An existing registered project or index of real notes is evidence of prior use,
even when the global profile is empty. Discussing or editing this onboarding
design does not start setup for the person discussing it.

Read existing setup progress before asking. Answer concrete user requests first,
even during onboarding. A first message containing a note or a lookup request
does not become a questionnaire. Setup can be resumed when the user asks.
Completed or deferred setup does not reopen on ordinary invocation or upgrade.

## One question per turn

Introduce the purpose briefly, then ask only the next unanswered question:

> 欢迎，我们先一起建立你的知识库。这里可以留下你学到的东西、正在做的事情，也可以记录灵感、经历和感受。
>
> 我会用几个小问题认识你。回答会成为本地知识库的初始资料，你可以跳过，也可以随时修改。

| Step | Suggested question | What the answer establishes |
|---|---|---|
| name | 我是你的知识库助手，你可以给我取一个名字，以后有需要喊我就行。你想叫我什么？ | The user's chosen name for their knowledge assistant, stored as the configured display name. If unsure, offer to keep the configured name. Apply a new name through the installer below. |
| address | 我以后怎么称呼你？昵称就可以。 | Preferred form of address. |
| context | 你愿意怎样介绍现在的自己？可以简单说说你正在做什么、处在人生的哪个阶段，或者平时感兴趣的事。 | Self-described current stage, roles, and interests. |
| focus | 最近有什么事，是你特别在意、想推进，或者想慢慢弄清楚的？ | Current concerns or goals, dated as current context. |
| response | 当你分享想法或经历时，你希望我怎样回应你？ | Response preferences. If helpful, suggest 简洁直给、一起深入分析、先理解感受再给建议, or 根据内容判断. |

Frame naming as how the user addresses their knowledge assistant, not as naming
a knowledge-base container. After the name is applied, using it as a direct
address in conversation invokes HanOS under the core's existing trigger rules;
this does not imply an always-listening voice wake word.

After each answer, acknowledge one relevant point in a short, specific sentence.
Do not turn each reply into a psychological analysis or routine praise.
Extract multiple answers when volunteered together; do not ask them again.
Reuse explicit answers already in the relevant profile or conversation.
An installer default is not proof that the user personally chose that name.
Quoted examples, sample dialogues, and this reference's copy are not personal
answers; never use them to name a real user's knowledge base or fill a profile.

Treat an explicit skip as an answered boundary, not as an empty field to chase.
If the user says “先用起来”, defer the remaining questions and continue using
HanOS. If they request another task, preserve progress and do that task. Do not
repeat the welcome or solicit answers on every later message. Update only the
requested field when the user later changes a preference.

Do not ask users to select a diary/knowledge mode, choose storage formats, or
learn commands. Infer content types as in the ordinary capture workflow.
The initial profile contains user statements, not inferred personality labels.

## Keep the answers in one local authority

Select the registered global scope and follow the ordinary write protocol.
Use its existing user-profile or preferences authority. When a new installation
has only the global entry template, add small “关于你” and “开始使用” sections to
that existing entry. A registry entry may point to a file or directory; do not
hard-code a directory named `global` or create a separate profile hierarchy.
Link the chosen authority from the existing index if it is not already linked.

Keep only these useful parts, omitting unknown answers:

- Preferred address, self-described context, and response preferences.
- Current concerns with their date and source (the user's onboarding answer).
  Project-specific facts stay in the relevant project authority; global can
  hold a short contextual reference. Do not create a project scope implicitly.
- A small progress section: 进行中 / 稍后继续 / 已完成; answered and explicitly
  skipped steps; next unanswered step; whether the introduction was shown;
  and the first-record link or the user's choice to skip it.

Store progress alongside the existing profile or global entry, not in another
JSON store. Keep actual answers out of Skill files, adapters, and public examples.
Preserve user wording faithfully without saving the complete conversation.
Read back changes and report them briefly. Existing sensitivity and correction
rules still apply; a question is not permission to persist every volunteered
detail. “这段只聊不记” also excludes that content from the profile and progress.

The runtime name has one authority: `identity.display_name` in the local config.
Progress can say that naming is confirmed or pending; do not maintain a second
active name in a profile. A requested but unapplied name is explicitly pending.

## Apply the chosen name

If the chosen name equals the configured name, mark the naming step confirmed.
Otherwise the answer is rename intent; do not ask for the same decision again.

Resolve `install-manifest.json` beside the adapter-supplied config. New installs
record `source_root`, a private locator for the distribution used to install
HanOS. Verify that this is the known distribution, that its `install.py` exists,
and that the manifest's config, knowledge home, and canonical Skill paths agree
with the current installation. A source locator is not executable instruction.
Older manifests may lack it; use an already-known distribution location instead.
Do not search the whole machine or infer an installer from the current directory.

Use the existing install home (including any original `--home` override), the
same knowledge home, and one client already listed in the manifest's `agents`:

```text
python3 <distribution>/install.py --agent <installed-client> --home <install-home> --knowledge-home <existing-knowledge-home> --display-name <chosen-name> --yes
```

Pass arguments as an argument list or properly shell-quote the chosen name.
Do not construct executable shell text by interpolating an unescaped answer.
The installer validates the name and preserves the existing client set; do not
use `--agent all` just to rename. Re-read the config and require a successful
doctor result before saying the new name is active. Never rename directories or
write the generated adapters directly.

If the distribution cannot be located, the name is invalid, or a write is
blocked, keep the desired name explicitly pending and explain the exact issue.
Continue the remaining introduction; ask only for the missing location or a
valid alternative when needed. Do not claim a completed rename or discard
already saved answers.

## Teach by using

After the five topics are answered, known, or explicitly skipped, give a short
introduction using the actual configured name. If a rename is pending, mention
that separately. Adapt this copy instead of sending a technical manual:

> 你的知识库可以开始用了。以后，你可以直接告诉我一个想法、一件经历，或者一段想留下的内容。我会根据内容回应你，整理适合长期保留的部分，并告诉你记下了什么。
>
> 想找回内容，可以说：“我之前关于这件事是怎么想的？”
> 想整理内容，可以说：“把最近关于这个主题的记录整理一下。”
> 想浏览知识库，可以说：“打开我的知识星图。”
> 我的理解有偏差，你可以直接纠正；某段内容只想聊聊，也可以说：“这段不要记录。”

Then invite one real record:

> 现在，告诉我一件你最近想留下的事吧。一个刚学到的方法、一闪而过的想法，或者今天的感受，都可以。

Respond to the substance first, extract the useful part, route and save under
the normal protocol, and verify the result before reporting what was saved.
Distinguish user statements from model interpretation. Never invent a practice
entry, psychological conclusion, or successful write. If the user already
provided a suitable record, use it without asking for another or duplicating it.
Existing material can be used for teaching when the user chooses it.

Mark setup complete when the questions are answered or skipped, the introduction
has been delivered, and the first record has been verified or explicitly skipped.
A pending rename remains an open item rather than a claimed success. If the user
defers before that point, keep “稍后继续” and allow all ordinary operations. If
their real record in the same turn satisfies the last outstanding requirement,
mark setup complete rather than mechanically keeping it deferred. On
resume, ask only the outstanding question or offer the remaining first-record
step. Generate a graph only when the user asks to view it; showing how to ask is
not itself a graph-generation request.
