"""
Core DocuBot class responsible for:
- Loading documents from the docs/ folder
- Building a simple retrieval index (Phase 1)
- Retrieving relevant snippets (Phase 1)
- Supporting retrieval only answers
- Supporting RAG answers when paired with Gemini (Phase 2)
"""

import os
import glob

# Common filler words that appear in almost every document. Matching on these
# creates false relevance (e.g. "what is the meaning of life" matching every
# doc because of "is"/"the"/"of"), so we ignore them during scoring.
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "is", "are", "was", "were", "be", "been", "do", "does", "did",
    "how", "what", "when", "where", "why", "who", "which", "this", "that",
    "these", "those", "it", "its", "as", "at", "by", "from", "i", "you", "we",
    "they", "my", "your", "can", "could", "would", "should", "will", "about",
    "into", "me", "so", "not", "no",
}


class DocuBot:
    def __init__(self, docs_folder="docs", llm_client=None):
        """
        docs_folder: directory containing project documentation files
        llm_client: optional Gemini client for LLM based answers
        """
        self.docs_folder = docs_folder
        self.llm_client = llm_client

        # Load documents into memory
        self.documents = self.load_documents()  # List of (filename, text)

        # Break documents into smaller paragraph sections. Sections, not whole
        # documents, are the unit we score and return. This keeps retrieved
        # text focused on the part that actually matches the query.
        self.sections = self.build_sections(self.documents)  # List of (filename, section)

        # Build a retrieval index over sections (implemented in Phase 1)
        self.index = self.build_index(self.sections)

    # -----------------------------------------------------------
    # Document Loading
    # -----------------------------------------------------------

    def load_documents(self):
        """
        Loads all .md and .txt files inside docs_folder.
        Returns a list of tuples: (filename, text)
        """
        docs = []
        pattern = os.path.join(self.docs_folder, "*.*")
        for path in glob.glob(pattern):
            if path.endswith(".md") or path.endswith(".txt"):
                with open(path, "r", encoding="utf8") as f:
                    text = f.read()
                filename = os.path.basename(path)
                docs.append((filename, text))
        return docs

    # -----------------------------------------------------------
    # Index Construction (Phase 1)
    # -----------------------------------------------------------

    def tokenize(self, text):
        """
        Turn text into a list of clean, lowercase words. Splits on whitespace
        and strips surrounding punctuation so "token," matches "token".
        Shared by indexing, scoring, and retrieval so they all agree on what
        counts as a word.
        """
        words = []
        for word in text.lower().split():
            word = word.strip(".,!?;:\"'()[]{}`#*")
            if word:
                words.append(word)
        return words

    def build_sections(self, documents):
        """
        Split each document into paragraph sections (separated by blank lines)
        and flatten them into one list of (filename, section_text) pairs.
        Sections are the unit of retrieval, so results stay focused instead of
        returning an entire file.
        """
        sections = []
        for filename, text in documents:
            for chunk in text.split("\n\n"):
                chunk = chunk.strip()
                if chunk:
                    sections.append((filename, chunk))
        return sections

    def build_index(self, sections):
        """
        Build a tiny inverted index mapping each meaningful lowercase word to
        the section indices it appears in. Section indices point into
        self.sections.

        Example structure:
        {
            "token": [0, 5],
            "database": [12]
        }

        Stopwords are skipped so common filler words don't point at every
        section.
        """
        index = {}
        for i, (_filename, text) in enumerate(sections):
            for word in self.tokenize(text):
                if word in STOPWORDS:
                    continue
                if word not in index:
                    index[word] = []
                # Avoid recording the same section twice for one word.
                if i not in index[word]:
                    index[word].append(i)
        return index

    # -----------------------------------------------------------
    # Scoring and Retrieval (Phase 1)
    # -----------------------------------------------------------

    def score_document(self, query, text):
        """
        Return a simple relevance score for how well the text matches the query.

        We count how many distinct *meaningful* query words (stopwords removed)
        appear as whole words in the text. Whole-word matching avoids spurious
        hits like "cat" matching "category".
        """
        text_words = set(self.tokenize(text))
        score = 0
        for word in self.tokenize(query):
            if word in STOPWORDS:
                continue
            if word in text_words:
                score += 1
        return score

    def retrieve(self, query, top_k=3, min_score=1):
        """
        Use the index and scoring function to select the top_k most relevant
        sections. Returns a list of (filename, section_text) sorted by score
        descending.

        Guardrail: only sections scoring at least `min_score` are returned. If
        the query has no meaningful words, or nothing clears the threshold, the
        result is empty and the caller reports "I do not know".
        """
        # Meaningful query words only. If the query is all filler ("what is
        # the..."), there is nothing to search for, so refuse up front.
        query_words = [w for w in self.tokenize(query) if w not in STOPWORDS]
        if not query_words:
            return []

        # Use the index to gather candidate sections: any section containing at
        # least one meaningful query word. This avoids scoring sections that
        # cannot match.
        candidates = set()
        for word in query_words:
            if word in self.index:
                candidates.update(self.index[word])

        # Score each candidate section and keep only those with real evidence.
        results = []
        for i in candidates:
            filename, text = self.sections[i]
            score = self.score_document(query, text)
            if score >= min_score:
                results.append((score, filename, text))

        # Sort by score descending, then drop the score for the return value.
        results.sort(key=lambda item: item[0], reverse=True)
        return [(filename, text) for _, filename, text in results[:top_k]]

    # -----------------------------------------------------------
    # Answering Modes
    # -----------------------------------------------------------

    def answer_retrieval_only(self, query, top_k=3):
        """
        Phase 1 retrieval only mode.
        Returns raw snippets and filenames with no LLM involved.
        """
        snippets = self.retrieve(query, top_k=top_k)

        if not snippets:
            return "I do not know based on these docs."

        formatted = []
        for filename, text in snippets:
            formatted.append(f"[{filename}]\n{text}\n")

        return "\n---\n".join(formatted)

    def answer_rag(self, query, top_k=3):
        """
        Phase 2 RAG mode.
        Uses student retrieval to select snippets, then asks Gemini
        to generate an answer using only those snippets.
        """
        if self.llm_client is None:
            raise RuntimeError(
                "RAG mode requires an LLM client. Provide a GeminiClient instance."
            )

        snippets = self.retrieve(query, top_k=top_k)

        if not snippets:
            return "I do not know based on these docs."

        return self.llm_client.answer_from_snippets(query, snippets)

    # -----------------------------------------------------------
    # Bonus Helper: concatenated docs for naive generation mode
    # -----------------------------------------------------------

    def full_corpus_text(self):
        """
        Returns all documents concatenated into a single string.
        This is used in Phase 0 for naive 'generation only' baselines.
        """
        return "\n\n".join(text for _, text in self.documents)
