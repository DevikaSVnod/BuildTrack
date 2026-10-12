# BuildTrack Global Search — client demo script

Login: `devika@buildtrack.com` / `password123`
Open: http://localhost:3000
Stay on any page. Use the search box at the top. Do not open a separate search page.

Rehearse once before the call. Document and drawing answers take about 10–20 seconds. While it thinks, use the “while it searches” line. Do not click away.

Type these queries exactly:

1. `who are the project managers`
2. `Risks & Considerations in commercial tower report`
3. `Components in the university plan`

---

## Opening (about 30 seconds)

“I’ll show Global Search inside BuildTrack, our construction project application.

People usually hunt for this information in three different places: the website itself — projects and people — then PDFs, and then drawings. Here it is one search box. You ask in normal language. The system decides where to look, finds the matching records, and writes a short answer with the source so you can open it.

I’ll show three questions. First people on the website, then a section inside a report, then components on a drawing.”

---

## 1. Search across the website

**Type:** `who are the project managers`

**While it searches:**

“This is not looking inside a file. It is looking across the application — the workforce records that sit behind the Team page.”

**When the answer appears, read it, then say:**

“It found two project managers.

Priya Nair, from NairTech Ltd, is on Commercial Tower Phase 2, the Industrial Warehouse, and Residential Complex A.

Sarah Chen, from ChenBuild Corp, is on the Highway Bridge, Metro Station Renovation, and also Residential Complex A.

Each result is a real person in the application. I can open that record from here. The same box can ask about projects, tasks, safety, or budget — anything that is already structured data on the site. I don’t have to know which menu it lives under.”

**If they ask you to try another website question, use one of these:**

- `Which projects are in progress?`
- `Who is on the workforce for Commercial Tower?`
- `High priority tasks on Highway Bridge`

---

## 2. Search across documents

**Type:** `Risks & Considerations in commercial tower report`

**While it searches:**

“This time the answer is not the file name. It is a section inside the PDF. The system looks through the text of the uploaded reports and brings back the passage that matches the question.”

**When the answer appears, say:**

“It opened the Commercial Tower Phase 2 planning report and pulled the risks from inside that document.

The main ones are permitting delays, material and labor cost movement, site logistics in a dense downtown area, weather, and extra team capacity as the job moves into construction.

The source is named under the answer: Commercial Tower Phase 2 Planning Report. So this is grounded in the file. It is not a general guess about construction risk.”

Point at the result row so they see the PDF.

---

## 3. Search across drawings

**Type:** `Components in the university plan`

**While it searches:**

“Drawings are different from Word and PDF reports. A lot of the meaning is in the picture — buildings, labels, the site layout — not in a paragraph. When the drawing is uploaded, we read the sheet and store what is on it. This question goes to that drawing, not to the text reports.”

**When the answer appears, say:**

“It matched the University Plan, sheet AM-789-C. That sheet is the proposed campus for Amity University, Jharkhand.

On the drawing it can see the instructional and admin block, boys’ and girls’ hostels, guest house, indoor sports complex, playground, the green belt, the HT line alignment, and the grading control points across the site.

So the same search box just moved from people, to a report, to a drawing — without the user choosing an index or a folder.”

Point at the drawing result titled **University Plan**.

---

## Close (about 20 seconds)

“What you just saw is one search experience over three kinds of content.

The website gives structured records: people, projects, tasks.
Documents give answers from inside the file.
Drawings give answers from what is on the sheet.

Underneath, the database stays the source of truth. Search only finds the best few matches. The AI writes the answer from those matches, and you always get the source so you can open the real record.”

Then stop and take questions.

---

## If they ask: how does this work?

Use this order. One idea per sentence. Stop when they nod.

### One sentence

“We index the data ahead of time, search that index when you type, then ask the model to answer only from the matches we just found.”

### The stack

| Piece | What it is | What to say |
|---|---|---|
| Website | Next.js | “The screen you are looking at.” |
| API | Python, FastAPI | “The search request goes to our API.” |
| Database | Azure SQL | “Projects, people, tasks, document records, and drawings live here. This is the source of truth.” |
| Files | Azure Blob Storage | “The actual PDF, Word file, or drawing image is stored here.” |
| Search | Azure AI Search | “This is the index. It is built for finding things quickly. We do not scan the whole database on every question.” |
| AI | Azure OpenAI | “One model writes the answer. Another turns text into meaning so we can match a question even when the wording is not exact. For drawings, a vision model reads the sheet at upload time.” |

Model names if they ask: answers use GPT-4o-mini. Meaning/search uses text-embedding-3-small embeddings.

### Ingestion — what happens before anyone searches

Say: “Nothing is searched live across every table and every file. We prepare three indexes, because the three kinds of content are different.”

**Website — people, projects, tasks**

“These are rows in SQL: a person, a role, a project, a task status.
We copy the searchable fields — name, role, project, title, status — into Azure AI Search.
The full record stays in SQL. When search finds an ID, we read that row again so the name and link on screen are current.
This refresh runs on a schedule, about every 15 minutes, and we can also push changes sooner.”

**Documents — reports and PDFs**

“When a file is uploaded, two things happen.
First, we store the file details: name, type, project, who uploaded it. That is how you find the document itself.
Second, we extract the text and split it into passages. Those passages are stored in a separate chunk index, with an embedding so we can match meaning, not only the exact words.
That is why ‘risks and considerations in the commercial tower report’ can land on a paragraph inside the PDF, not just on a file whose name contains those words.”

**Drawings**

“A drawing is mostly a picture.
On upload, a vision model looks at the sheet and writes a structured inventory: what objects are on it, how many, and the labels printed on the drawing.
We also keep the drawing number, title, discipline, and any sheet notes in the search index so we can find the right sheet.
‘Components in the university plan’ is recognized as a drawing question. We find the University Plan, then answer from that inventory.”

### Retrieval — what happens when you press Enter

Walk this as four steps. This is the part they will remember.

“Step one. We read the question and decide the type.
‘Who are the project managers’ is a people question, so we look at workforce records.
‘Risks in the commercial tower report’ is a document question, so we look at passages inside files.
‘Components in the university plan’ is a drawing question, so we look at drawings.
The user does not pick a filter. The wording does it.”

“Step two. Azure AI Search finds the best matches.
It uses keywords, meaning from embeddings, and semantic ranking together. That is hybrid search.
It returns a short list, not the whole database.”

“Step three. We go back to SQL for those few matches.
The index told us which person, which file, or which drawing. The database gives us the current record and the link to open it.”

“Step four. Azure OpenAI writes the answer from that short list only.
It is not browsing the internet, and it is not reading every project in the database.
If nothing relevant comes back, it says it could not find it, instead of inventing an answer.
You always see the source next to the answer.”

### The line that prevents the most common objection

“The language model does not sit on top of the database and scan it.
Search finds a handful of candidates. The model only sees those candidates. That is why the answer cites a person, a PDF, or a drawing number.”

---

## Likely questions

**Is this searching the live website, or a copy?**
“The records are created and updated in the application database. Search uses an index built from that database so the question is fast. After we have the matching IDs, we read the live rows again.”

**How fresh is it?**
“Structured data is synced on a schedule of about 15 minutes, and we can push changes sooner. A new document or drawing becomes searchable after upload processing finishes: text extraction for a report, vision inventory for a drawing. It is not instant for every sentence typed into the database.”

**What if the PDF is a scan?**
“If there is no extractable text, there is nothing to search inside the file. We can still find it by name. For a scanned report we would need OCR. Drawings are handled differently, because vision reads the image.”

**Can it answer from a drawing that was never uploaded here?**
“No. It only knows drawings that have been uploaded and processed into this application.”

**Does it respect who is allowed to see a project?**
“Yes. Search can be trimmed by project access, so a user only gets hits for projects they belong to. In this demo we are logged in as an admin, so you see the full set.”

**Can you add more systems later?**
“Yes. Each new database or module is another source with the same pattern: keep the system of record where it is, index the searchable fields, route the question to the right source, and answer from the matches. BuildTrack is the source in this demo.”

**Why not just give the question to ChatGPT with the whole database?**
“Cost, speed, and trust. A full scan would be slow and expensive, and the model would mix sources. Here we retrieve first, then answer, and we show the source.”

---

## Demo-day checklist

- Log in before they join. Leave the search box empty.
- Have the three queries in a notepad so you can paste them. Typing live is fine if you are comfortable; paste if the call is short.
- First query is the fastest. Use it to settle the room.
- Expect about 15 seconds on the report, and a few seconds on the drawing.
- Do not switch tabs while an answer is generating.
- If an answer looks thin, read the source name on screen and say: “Let me open that source.” Do not invent a number that is not on screen.

**Expected results, so you know the demo worked**

1. Priya Nair and Sarah Chen, both tagged as people on BuildTrack.
2. Commercial Tower Phase 2 Planning Report PDF, with permitting, cost, logistics, weather, and team capacity.
3. Drawing titled University Plan, sheet AM-789-C, Amity University campus: hostels, admin block, sports complex, playground, green belt, HT lines, grading control points.
