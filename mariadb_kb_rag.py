import mariadb
import sys
from openai import OpenAI
import os
import requests
from bs4 import BeautifulSoup
import html2text
import time
import json

def delete_database(cur):
   print("Delete database")
   cur.execute("""DROP DATABASE IF EXISTS kb_vector;""")

def create_database_and_tables(cur): 
   print("Creating database and tables")
   cur.execute("""
      CREATE DATABASE IF NOT EXISTS kb_vector;
      """)
   cur.execute("""
      CREATE TABLE IF NOT EXISTS kb_vector.kb_articles (
         article_id INT PRIMARY KEY AUTO_INCREMENT,
         title VARCHAR(255) NOT NULL,
         url VARCHAR(255) UNIQUE NOT NULL,
         content LONGTEXT NOT NULL
      );
      """)
   cur.execute("""
      CREATE TABLE IF NOT EXISTS kb_vector.kb_chunks (
         chunk_id INT PRIMARY KEY AUTO_INCREMENT,
         article_id INT,
         chunk_order INT,
         chunk_content LONGTEXT NOT NULL,
         embedding VECTOR(1536) NOT NULL, 
         VECTOR INDEX (embedding), 
         FOREIGN KEY (article_id) REFERENCES kb_articles(article_id)
      );
      """)

def scrape_kb():
   print("Reading KB content from scraped web")
   contents = []
   contents.append({"url" : "https://mariadb.com/kb/en/vector-overview/"})
   contents.append({"url" : "https://mariadb.com/kb/en/what-is-mariadb-galera-cluster/"})
   
   ## Configure html2text for markdown conversion
   h = html2text.HTML2Text()
   h.ignore_links = False
   h.ignore_images = False
   h.body_width = 0  # Don't wrap text at a specific width
   
   for content in contents:
      url = content["url"]
      print("Scraping: ", url)
      response = requests.get(url)
      if response.status_code == 404:
         print("Error")
         continue
      soup = BeautifulSoup(response.content, "html.parser")
      content["title"] = soup.find("h1").text.strip()
      content_html = str(soup.find("div", class_="answer formatted"))
      content["content"] = h.handle(content_html) # Convert HTML to markdown
      print(f"Scraped content: {content["title"]}")
      #print(content["content"])
   return contents

def read_kb_from_file():
   filename = "kb_scraped_md.jsonl"
   print(f"Reading KB content from {filename} file")
   contents = []
   with open(filename, "r") as file:
      for line in file:
         content = json.loads(line)
         contents.append(content)
   return contents

def insert_content_to_mdb(cur, conn, contents):
   print("Inserting KB content to MariaDB table kb_articles")
   for content in contents: 
      cur.execute("""INSERT INTO kb_vector.kb_articles (title, url, content)
                  VALUES (%s, %s, %s)""",
                  (content["title"], content["url"], content["content"]))
      conn.commit()

def get_content_from_mdb(cur):
   print("Getting content from MariaDB kb_articles")
   items = []
   cur.execute("SELECT article_id, title, url, content FROM kb_vector.kb_articles")
   for (article_id, title, url, content) in cur:
      items.append({
             "id":article_id, 
             "title":title, 
             "url":url, 
             "content":content
             })
   print(f"Retrieved items: {len(items)}\n")
   return items

def chunkify(content, min_chars=2000, max_chars=10000):
    lines = content.split('\n')
    final_chunks = []
    current_chunk = []
    current_length = 0
    current_start_line = 0
    
    for i, line in enumerate(lines):
        # Check if line is a header (markdown style) or empty line (paragraph break)
        is_header = line.lstrip().startswith('#')
        is_paragraph_break = line.strip() == ''
        
        # If we have content in current_chunk, check if we should start a new chunk
        if current_chunk and (
            (is_header or is_paragraph_break or current_length + len(line) > max_chars) and
            current_length >= min_chars
        ):
            chunk_text = '\n'.join(current_chunk).strip()
            if chunk_text:
                final_chunks.append({
                    'content': chunk_text,
                    'start_line': current_start_line,
                    'end_line': i - 1  # -1 because we haven't included the current line
                })
            current_chunk = []
            current_length = 0
            current_start_line = i
        
        # Skip empty lines only if we have content and meet the minimum length
        if not line.strip() and current_length >= min_chars:
            continue
            
        # Add line to current chunk
        current_chunk.append(line)
        current_length += len(line) + 1  # +1 for newline
    
    # Add any remaining content
    if current_chunk:
        chunk_text = '\n'.join(current_chunk).strip()
        if chunk_text:
            final_chunks.append({
                'content': chunk_text,
                'start_line': current_start_line,
                'end_line': len(lines) - 1
            })
    
    return final_chunks

# 
def embed(text):
   #print(f"embedding {text}")
   response = client.embeddings.create(
   input = text,
   model = "text-embedding-3-small" # max 8192 tokens (roughly 32k chars)
   )
   embedding = response.data[0].embedding
   return embedding

def insert_chunks_and_embedding(cur, conn, items):
     start_time = time.time()
     total_chunks = 0
     total_articles = len(items)
     total_embed_time = 0
     total_vector_insert_time = 0

     for j, item in enumerate(items):
         article_start = time.time()
         total_lines = len(item["content"].split('\n'))
         article_length = len(item['content'])
         content = item["content"]
         chunks = chunkify(content)
         total_chunks += len(chunks)

         for i, chunk in enumerate(chunks):
            #print(chunk['content'])
            embed_start = time.time()
            embedding = embed(chunk['content'])
            embed_time = time.time() - embed_start
            vector_insert_start = time.time()

            cur.execute(
                """INSERT INTO kb_vector.kb_chunks 
                   (article_id, chunk_order, chunk_content, embedding) 
                VALUES (%d, %d, %s, VEC_FromText(%s))""",
                (item["id"], i, chunk['content'], str(embedding))
            )

            vector_insert_time = time.time() - vector_insert_start
            total_vector_insert_time += vector_insert_time

            print(f"Embedded chunk {i+1}/{len(chunks)}, page {j+1}/{len(items)} '{item["title"]}', lines {chunk['start_line']}-{chunk['end_line']} of {total_lines}, length {len(chunk['content'])} of article {article_length}. Embed {embed_time:.2f} s, MariaDB insert {vector_insert_time:.2f} s")

         #print("Doing commit")
         vector_insert_start = time.time()
         conn.commit() 
         vector_insert_time = time.time() - vector_insert_start
         total_vector_insert_time += vector_insert_time 

         article_time = time.time() - article_start
         print(f"Inserting {len(chunks)} chunks from page {j} '{item["title"]}' to MariaDB kb_chunks")
         print(f"Article processing time: {article_time:.2f} seconds. So far total embedding time: {total_embed_time:.2f} seconds, vector insert time: {total_vector_insert_time:.2f} seconds")
   
     total_time = time.time() - start_time
     avg_time = total_time / total_chunks if total_chunks > 0 else 0
     avg_article_time = total_time / total_articles if total_articles > 0 else 0
     print(f"\nEmbedding Statistics:")
     print(f"Total processing time: {total_time:.2f} seconds")
     print(f"Total articles processed: {total_articles}")
     print(f"Average time per article: {avg_article_time:.2f} seconds")
     print(f"Total chunks processed: {total_chunks}")
     print(f"Average time per chunk: {avg_time:.2f} seconds")
     print(f"Total embedding time: {total_embed_time:.2f} seconds")
     print(f"Average embedding time per chunk: {total_embed_time / total_chunks:.2f} seconds")
     print(f"Total vector insert time: {total_vector_insert_time:.2f} seconds")
     print(f"Average vector insert time per chunk: {total_vector_insert_time / total_chunks:.2f} seconds")

def count_chunks_in_mariadb(cur):
   print("\nTotal chunks in MariaDB kb_chunks:")
   cur.execute("""
      SELECT COUNT(*) as total_chunks, 
             COUNT(DISTINCT article_id) as unique_articles 
      FROM kb_vector.kb_chunks""")
   for (total_chunks, unique_articles) in cur:
      print(f"Total articles: {unique_articles}")
      print(f"Total chunks: {total_chunks}")

def search_for_closest(cur, text, n, previous=0, next=0):
   print(f"\nSearching for {n} closest chunks to: '{text}'")
   embedding = embed(text)
   closest_chunks = []
   
   query_start = time.time()
   cur.execute("""
WITH closest_vectors AS (
   SELECT chunk_id, article_id, chunk_order,
      VEC_DISTANCE_EUCLIDEAN(embedding, VEC_FromText(%s)) AS distance
   FROM kb_vector.kb_chunks
   ORDER BY distance
   LIMIT %s
),
closest_chunks AS (
   SELECT cv.chunk_id, cv.chunk_order, c.chunk_content,
      a.article_id, a.title, a.url, cv.distance
   FROM closest_vectors cv
   JOIN kb_vector.kb_chunks c ON cv.chunk_id = c.chunk_id
   JOIN kb_vector.kb_articles a ON cv.article_id = a.article_id
)
SELECT c2.chunk_order, c2.chunk_content,
   cc.article_id, cc.title, cc.url,
   CASE 
      WHEN c2.chunk_order = cc.chunk_order THEN 'main'
      WHEN c2.chunk_order < cc.chunk_order THEN 'previous'
      ELSE 'next'
   END AS chunk_type,
   cc.distance
FROM closest_chunks cc
JOIN kb_vector.kb_chunks c2 ON c2.article_id = cc.article_id
WHERE c2.chunk_order BETWEEN (cc.chunk_order - %s) AND (cc.chunk_order + %s)
ORDER BY cc.distance, cc.article_id, c2.chunk_order;

    """, (str(embedding), n, previous, next))
    
   for (chunk_order, chunk_content, article_id, title, url, chunk_type, distance) in cur:
      closest_chunks.append({
         "article_id": article_id,
         "url": url,
         "title": title,
         "chunk_order": chunk_order,
         "chunk_type": chunk_type,
         "chunk_content": chunk_content,
         "distance": distance
        })

   result = f"\nClosest {n} chunks:"
   for chunk in closest_chunks:
      result += f"\n{chunk["distance"]}, {chunk["url"]}, chunk {chunk["chunk_order"]}, {chunk["chunk_type"]}: {chunk["chunk_content"].replace('\n', ' ')}"
   #print(f"{result}")
   query_time = time.time() - query_start
   #print(f"Vector search query time: {query_time:.2f} seconds")

   return closest_chunks, query_time

def prompt_llm(question, closest_chunks):
   sources = ""
   if closest_chunks is None:
      print(f"Prompting LLM without closest chunks for question: '{question}'")
      prompt = f"""
      You are a helpful assistant that answers questions using exclusively about MariaDB.
      The user asked: {question}
      """
   else:
      print(f"\nPrompting LLM with {len(closest_chunks)} closest chunks and question: '{question}'")
      prompt = f"""
      You are a helpful assistant that answers questions using exclusively the MariaDB Knowledge Base that you are provided with.
      The user asked: {question}
      Use only the following content from the MariaDB Knowledge Base to answer the question. If the content does not answer the question, say so.
      """
      for chunk in closest_chunks:
         prompt += f"""
Title: {chunk["title"]}
Url: {chunk["url"]}
Chunk order number: {chunk["chunk_order"]}
Chunk content: {chunk["chunk_content"]}
         """
      sources = "\n\nClosest Knowledge Base content shared with LLM:\n"
      for chunk in closest_chunks:
         sources += f"{chunk["distance"]}, [{chunk["title"]}]({chunk["url"]}, chunk {chunk["chunk_order"]}, {chunk["chunk_content"].replace('\n', ' ')[:20]} ... {chunk["chunk_content"].replace('\n', ' ')[-20:]}\n"   

   response = client.chat.completions.create(
      model="gpt-4o-mini",
      messages=[{"role": "system", "content": prompt}]
   )
   answer = "\nResponse from LLM:\n"
   answer += response.choices[0].message.content
   print(answer)
   return f"{answer}{sources}"

def prepare_database(source="scraped"):
    """Set up the database and load initial content"""
    try:
        conn = get_database_connection()
        cur = conn.cursor()
        
        # Prepare tables
        delete_database(cur)
        create_database_and_tables(cur)
        
        # Insert KB articles
        #contents = scrape_kb()
        if source == "scraped":
            contents = scrape_kb()
        elif source == "file":
            contents = read_kb_from_file()
        else:
           exit(f"Unknown source: {source}")
        insert_content_to_mdb(cur, conn, contents)
        
        # Create chunks and embeddings
        items = get_content_from_mdb(cur)
        insert_chunks_and_embedding(cur, conn, items)
        
        count_chunks_in_mariadb(cur)
        conn.close()
        
    except mariadb.Error as e:
        print(f"Error in database on line {sys.exc_info()[2].tb_lineno} in function {sys._getframe().f_code.co_name}: {e}")
        sys.exit(1)


def get_database_connection():
    """Create and return a database connection"""
    return mariadb.connect(
        host="127.0.0.1",
        port=3306,
        user="root",
        password="Password123!"
    )

def answer_questions(questions):
    """Process a list of questions using the prepared database"""
    try:
        conn = get_database_connection()
        cur = conn.cursor()
        
        for question in questions:
            time_answer_q_start = time.time()
            time_search_start = time.time()
            closest_chunks, vector_search_time = search_for_closest(cur, question, n=5, next=0, previous=0)
            time_search_end = time.time()
            answer = prompt_llm(question, closest_chunks=None)
            answer = prompt_llm(question, closest_chunks)
            time_answer_q_end = time.time()
            print(f"Total time to answer question: {time_answer_q_end - time_answer_q_start:.2f} seconds")
            print(f"Time to embed question and vector search for closest chunks: {time_search_end - time_search_start:.2f} seconds")
            print(f"Vector search time: {vector_search_time:.2f} seconds")
            print(f"Time to prompt LLM: {time_answer_q_end - time_search_end:.2f} seconds")
            print(f"\n\n")
        conn.close()
        
    except mariadb.Error as e:
        print(f"Error in question answering: {e}")
        sys.exit(1)


# To run MariaDB 11.7.1 with Docker: 
# docker run -p 127.0.0.1:3306:3306  --name mdb_1171 -e MARIADB_ROOT_PASSWORD=Password123! -d quay.io/mariadb-foundation/mariadb-devel:11.7

# For embedding, OpenAI API key is needed. Create at https://platform.openai.com/api-keys and add to system variables with export OPENAI_API_KEY='your-key-here'.

client = OpenAI(
   api_key=os.getenv('OPENAI_API_KEY') 
)

prepare_database(source="scraped")

questions = [
   "Is MariaDB compatible with MySQL?",
   "tell me more about MariaDB Oracle mode",
   "where can MariaDB Galera Cluster be downloaded?", 
   "What data types should be used for vector data?", 
   "create vector index"
   ]

answer_questions(questions)
