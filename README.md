# MariaDB Knowledge Base RAG with Vector Search

A Python script that implements Retrieval-Augmented Generation (RAG) on the MariaDB Knowledge Base using MariaDB's vector database capabilities, OpenAI's embedding model, and OpenAI's LLM.

## Features

1. Scrapes MariaDB Knowledge Base articles
2. Converts HTML content to markdown format
3. Chunks articles into manageable segments
4. Creates embedding for each chunk using OpenAI's text-embedding-3-small model
5. Stores content and embeddings in MariaDB vector database
6. Takes a "question" as input
7. Searches for most relevant chunks using vector similarity
8. Generates responses using LLM (GPT-4) with relevant KB context

## Prerequisites

- Docker
- Python 3.x (developed with 3.13)
- OpenAI API key
- MariaDB 11.6 Vector Preview Release

## Setup

1. Start MariaDB 11.6 Vector Preview with Docker: 

```bash
docker run -p 127.0.0.1:3306:3306  --name mdb_116_vector -e MARIADB_ROOT_PASSWORD=Password123! -d quay.io/mariadb-foundation/mariadb-devel:11.6-vector-preview
```

If needed, access MariaDB with:

```bash
docker exec -it mdb_116_vector mariadb --user root -pPassword123!
```

2. Add your OpenAI API key to your environment variables. Create a key at https://platform.openai.com/api-keys. 

```bash
export OPENAI_API_KEY='your-key-here'
```

3. Set up a virtual environment

```bash
python -m venv venv
source venv/bin/activate  # On Unix/macOS
```

4. Install the required Python packages with pip

```bash
pip install -r requirements.txt
```

## Usage

Running the following  at the moment does everything from setting up the database, to printing a LLM response to a question.

```bash
python mariadb_kb_rag.py
```

## Possible next todos

- Separate preparation and question asking for easier running
- Test with larger amount of KB data
- Improve efficiency: add caching for KB scraping, ignore scraping and inserting content already in database, etc
- Try with other embedding and LLM models
- Graphical GUI somehow

Recently done:

- Add timer for embedding and vector search
- Improve chunkification with a max char limit (prioritize paragraph, then new line, then forced cut)

## Resources used to put this together

- Cursor https://www.cursor.com/
- MariaDB Vector https://mariadb.com/kb/en/vector-overview/
- MariaDB Vector example https://mariadb.com/resources/blog/mariadb-vector-preview-is-out/
- Installing and Using MariaDB via Docker https://mariadb.com/kb/en/installing-and-using-mariadb-via-docker/