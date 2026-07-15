# DocuBot Model Card

This model card is a short reflection on your DocuBot system. Fill it out after you have implemented retrieval and experimented with all three modes:

1. Naive LLM over full docs  
2. Retrieval only  
3. RAG (retrieval plus LLM)

Use clear, honest descriptions. It is fine if your system is imperfect.

---

## 1. System Overview

**What is DocuBot trying to do?**  
Describe the overall goal in 2 to 3 sentences.

> DocuBot answers developer questions about a small set of project docs
> (`AUTH.md`, `API_REFERENCE.md`, `DATABASE.md`, `SETUP.md`). Its goal is to
> give answers that are *grounded* in those docs rather than in the model's
> prior knowledge, and to refuse when the docs do not contain the answer.

**What inputs does DocuBot take?**  
For example: user question, docs in folder, environment variables.

> A user question (typed at the CLI), the Markdown/text files in the `docs/`
> folder, and the `GEMINI_API_KEY` environment variable (only needed for the
> LLM modes).

**What outputs does DocuBot produce?**

> Depending on the mode: an LLM answer over the full corpus (Naive), the raw
> retrieved snippets with their filenames (Retrieval only), or a concise,
> snippet-grounded answer that cites its source files (RAG). Any mode can
> return "I do not know based on the docs I have."

---

## 2. Retrieval Design

**How does your retrieval system work?**  
Describe your choices for indexing and scoring.

- How do you turn documents into an index?
- How do you score relevance for a query?
- How do you choose top snippets?

> **Index:** Documents are split into paragraph *sections* (on blank lines),
> and an inverted index maps each meaningful lowercase word to the section
> indices it appears in. Common stopwords (`the`, `is`, `of`, `how`, ...) are
> skipped so filler words don't point at every section.
>
> **Scoring:** For a query, I strip stopwords and count how many distinct
> query words appear as *whole words* in a section (whole-word match avoids
> "cat" matching "category").
>
> **Top snippets:** I gather candidate sections from the index, score each,
> keep only those scoring `>= min_score` (default 1), sort by score
> descending, and return the top `k` (default 3) as `(filename, section)`.

**What tradeoffs did you make?**  
For example: speed vs precision, simplicity vs accuracy.

> I chose **simplicity over recall**. Keyword whole-word matching is easy to
> reason about and fast, but it has no understanding of synonyms — "logged
> out" won't match "token lifetime." Paragraph sections give focused snippets
> but can split an answer that spans two paragraphs. `min_score=1` favors
> recall (one keyword is enough); raising it would cut noise but refuse more.

---

## 3. Use of the LLM (Gemini)

**When does DocuBot call the LLM and when does it not?**  
Briefly describe how each mode behaves.

- Naive LLM mode: Stuffs the **entire docs corpus** into one prompt and asks
  the model to answer. No retrieval, no strict grounding rules.
- Retrieval only mode: **No LLM at all.** Returns the raw retrieved sections.
- RAG mode: Runs retrieval first, then sends **only those snippets** to the
  LLM with strict grounding rules.

> Note: I fixed `naive_answer_over_full_docs`, which had been ignoring the
> corpus and sending a generic prompt, so the "naive over full docs" baseline
> now actually uses the docs. I also updated the model to `gemini-flash-latest`
> because the configured `gemma-3-27b-it` returned 404 for this key.

**What instructions do you give the LLM to keep it grounded?**  
Summarize the rules from your prompt. For example: only use snippets, say "I do not know" when needed, cite files.

> The RAG prompt tells the model to: (1) answer using **only** the provided
> snippets, (2) not invent functions, endpoints, or config values, (3) reply
> exactly "I do not know based on the docs I have." when the snippets are
> insufficient, and (4) mention which files it relied on.

---

## 4. Experiments and Comparisons

Run the **same set of queries** in all three modes. Fill in the table with short notes.

You can reuse or adapt the queries from `dataset.py`.

| Query | Naive LLM: helpful or harmful? | Retrieval only: helpful or harmful? | RAG: helpful or harmful? | Notes |
|------|---------------------------------|--------------------------------------|---------------------------|-------|
| How is the database connection configured? | Helpful but verbose — correct, even adds `db.py` internals not asked for | Helpful — 3 accurate `DATABASE.md` snippets, reader assembles them | **Best** — concise, answers directly, cites `DATABASE.md` | All three correct; RAG has best clarity-per-evidence |
| How long is an auth token valid before it expires? | Helpful — cites `TOKEN_LIFETIME_SECONDS`, 3600s | Helpful — exact snippet, but raw | **Best** — "defaults to 3600 seconds (1 hour)" + cites `AUTH.md` | RAG answer is traceable to a file |
| How do I deploy this app to Kubernetes? | **Harmful** — confidently invents ConfigMaps, Secrets, Helm, port 5000 (no k8s in docs) | Weak — returns one unrelated `DATABASE_URL` snippet | **Best** — refuses: "I do not know based on the docs I have." | The clearest win for grounding |
| How long until I get logged out of my session? | (would likely bridge synonyms from full corpus) | Noisy — good `TOKEN_LIFETIME` snippet buried between `GET /api/projects` headers | **Fails** — false refusal despite answer being retrievable | Vocabulary gap: "logged out" vs "token lifetime" |

**What patterns did you notice?**  

- When does naive LLM look impressive but untrustworthy?  
- When is retrieval only clearly better?  
- When is RAG clearly better than both?

> **Naive** looks impressive but is untrustworthy when the docs are *silent* —
> the Kubernetes question produced a long, authoritative answer that was mostly
> model prior, not evidence. **Retrieval only** is better when you need to
> verify the exact source text and don't trust any synthesis, but it's hard to
> read. **RAG** is clearly best when the answer *is* in the docs: it turns the
> same snippets into a concise, cited answer and refuses cleanly when nothing
> relevant is retrieved.

---

## 5. Failure Cases and Guardrails

**Describe at least two concrete failure cases you observed.**  
For each one, say:

- What was the question?  
- What did the system do?  
- What should have happened instead?

> **Failure case 1 (Naive hallucination):** "How do I deploy this app to
> Kubernetes?" — Naive mode confidently produced detailed Kubernetes
> deployment guidance (ConfigMaps, Secrets, Helm, port 5000) that is not in the
> docs. It should have said the docs contain no Kubernetes instructions
> (which RAG did).

> **Failure case 2 (RAG false refusal):** "How long until I get logged out of
> my session?" — RAG replied "I do not know based on the docs I have," even
> though `TOKEN_LIFETIME_SECONDS` answers it and retrieval even surfaced that
> snippet. Two irrelevant `GET /api/projects` sections diluted the context and
> the "session/logged out" vs "token lifetime" vocabulary gap stopped the
> strict model from bridging them. It should have answered ~3600 seconds.

**When should DocuBot say "I do not know based on the docs I have"?**  
Give at least two specific situations.

> (1) When no section contains any meaningful (non-stopword) query term — e.g.
> a topic the docs never cover, like Kubernetes. (2) When the retrieved
> snippets exist but don't actually contain enough evidence to answer the
> specific question, so the LLM shouldn't guess.

**What guardrails did you implement?**  
Examples: refusal rules, thresholds, limits on snippets, safe defaults.

> Two layers. **Retrieval layer:** refuse (return no snippets) when the query
> has no meaningful words or no section clears `min_score`; cap results at
> `top_k`. **LLM layer:** the RAG prompt forbids inventing details and
> mandates the exact "I do not know..." refusal when snippets are
> insufficient. Both `answer_retrieval_only` and `answer_rag` return a safe "I
> do not know" default on empty retrieval.

---

## 6. Limitations and Future Improvements

**Current limitations**  
List at least three limitations of your DocuBot system.

1. **No synonym/semantic understanding** — keyword matching misses answers
   phrased differently than the docs (the "logged out" false refusal).
2. **Noisy retrieval** — short section headers (`### GET /api/projects`) can
   match a single keyword and crowd out the genuinely relevant section.
3. **Answers can be split across sections** — paragraph chunking can separate a
   heading from the detail that answers the question.
4. **Depends on an external API** — transient `503`/`429` errors block the LLM
   modes; retrieval-only still works.

**Future improvements**  
List two or three changes that would most improve reliability or usefulness.

1. Use **embeddings / semantic search** so synonyms and paraphrases match.
2. Add **scoring signals beyond raw counts** (term frequency, penalize very
   short header-only sections) to reduce noisy matches.
3. Show **scores/confidence** alongside snippets and tune `min_score` so
   borderline questions are handled more transparently.

---

## 7. Responsible Use

**Where could this system cause real world harm if used carelessly?**  
Think about wrong answers, missing information, or over trusting the LLM.

> The Naive mode shows the danger: a developer could follow confident but
> fabricated instructions (e.g. invented config values or deployment steps)
> and misconfigure security-sensitive settings like auth tokens or database
> connections. Missing information presented as a complete answer is the main
> risk — a wrong config change can leak data or break production.

**What instructions would you give real developers who want to use DocuBot safely?**  
Write 2 to 4 short bullet points.

- Prefer **RAG mode** and treat the cited files as the source of truth —
  verify any answer against the referenced doc before acting on it.
- Trust "I do not know" — it means the docs don't cover it, not that the
  answer is trivial; go read the code or ask a human.
- Be skeptical of long, confident answers with **no file citations** (a sign
  of ungrounded generation).
- Remember retrieval is keyword-based: rephrase using the docs' own terms if a
  real question gets refused.

---
