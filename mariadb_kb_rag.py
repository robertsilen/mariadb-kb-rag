import mariadb
import sys
from openai import OpenAI
import os
import requests
from bs4 import BeautifulSoup
import html2text
import time

def delete_database(cur):
   print("Delete database")
   cur.execute("""DROP DATABASE IF EXISTS kb_vector;""")

def create_tables(cur): 
   print("Creating database and tables")
   cur.execute("""
      CREATE DATABASE IF NOT EXISTS kb_vector;
      """)
   cur.execute("""
      CREATE TABLE IF NOT EXISTS kb_vector.kb_articles (
         article_id INT PRIMARY KEY AUTO_INCREMENT,
         title VARCHAR(255) NOT NULL,
         slug VARCHAR(255) UNIQUE NOT NULL,
         content LONGTEXT NOT NULL
      );
      """)
   cur.execute("""
      CREATE TABLE IF NOT EXISTS kb_vector.kb_chunks (
         chunk_id INT PRIMARY KEY AUTO_INCREMENT,
         article_id INT,
         chunk_order INT,
         chunk_content LONGTEXT NOT NULL,
         embedding BLOB NOT NULL, 
         VECTOR INDEX (embedding), 
         FOREIGN KEY (article_id) REFERENCES kb_articles(article_id)
      );
      """)

def read_kb_from_slugs():
   print("Reading KB content from scraped web")
   contents = []
   contents.append({"slug" : "/en/vector-overview/"})
   contents.append({"slug" : "/en/what-is-mariadb-galera-cluster/"})

   ## Read in more slugs from file 
   #filename = "kb_slugs.txt"
   #with open(filename, "r") as file:
   #   for line in file:
   #      contents.append({"slug" : line.strip()})
   
   ## Configure html2text
   h = html2text.HTML2Text()
   h.ignore_links = False
   h.ignore_images = False
   h.body_width = 0  # Don't wrap text at a specific width
   
   for content in contents:
      url = "https://mariadb.com/kb" + content["slug"]
      print("Scraping: ", url)
      response = requests.get(url)
      if response.status_code == 404:
         print("Error")
         continue
      soup = BeautifulSoup(response.content, "html.parser")
      content["title"] = soup.find("h1").text.strip()
      content_html = str(soup.find("div", class_="answer formatted"))
      content["content"] = h.handle(content_html) # Convert HTML to markdown
      print("Scraped content: ", url, content["title"])
      #print(content["content"])
   return contents

def insert_content_to_mdb(cur, contents):
   print("Inserting KB content to MariaDB table kb_articles")
   for content in contents: 
      cur.execute("""INSERT INTO kb_vector.kb_articles (title, slug, content)
                  VALUES (%s, %s, %s)""",
                  (content["title"], content["slug"], content["content"]))
      conn.commit()

def get_content_from_mdb(cur):
   print("Getting content from MariaDB kb_articles")
   items = []
   cur.execute("SELECT article_id, title, slug, content FROM kb_vector.kb_articles")
   for (article_id, title, slug, content) in cur:
      items.append({
             "id":article_id, 
             "title":title, 
             "slug":slug, 
             "content":content
             })
   print("Retrieved items: ", len(items))
   return items

def chunkify(content, max_chars=6000):
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
            is_header or 
            is_paragraph_break or 
            current_length + len(line) > max_chars
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
        
        # Skip empty lines
        if not line.strip():
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

def insert_chunks_and_embedding(items):
     start_time = time.time()
     total_chunks = 0
     total_articles = len(items)
     
     for j, item in enumerate(items):
         article_start = time.time()
         content = item["content"]
         chunks = chunkify(content)
         total_chunks += len(chunks)
         
         for i, chunk in enumerate(chunks):
            chunk_start = time.time()
            total_lines = len(content.split('\n'))
            article_length = len(item['content'])
            print(f"Embedding chunk {i} from page {j} '{item["title"]}', lines {chunk['start_line']}-{chunk['end_line']} of total lines {total_lines}, chunk length {len(chunk['content'])} of article length {article_length}")
            #print(chunk['content'])
            embedding = embed(chunk['content'])
            cur.execute(
                """INSERT INTO kb_vector.kb_chunks 
                   (article_id, chunk_order, chunk_content, embedding) 
                VALUES (%d, %d, %s, Vec_FromText(%s))""",
                (item["id"], i, chunk['content'], str(embedding))
            )
            chunk_time = time.time() - chunk_start
            #print(f"Chunk processing time: {chunk_time:.2f} seconds")
            
         article_time = time.time() - article_start
         print(f"Inserting {len(chunks)} chunks from page {j} '{item["title"]}' to MariaDB kb_chunks")
         print(f"Article processing time: {article_time:.2f} seconds")
         conn.commit()
     
     total_time = time.time() - start_time
     avg_time = total_time / total_chunks if total_chunks > 0 else 0
     avg_article_time = total_time / total_articles if total_articles > 0 else 0
     print(f"\nEmbedding Statistics:")
     print(f"Total processing time: {total_time:.2f} seconds")
     print(f"Total articles processed: {total_articles}")
     print(f"Average time per article: {avg_article_time:.2f} seconds")
     print(f"Total chunks processed: {total_chunks}")
     print(f"Average time per chunk: {avg_time:.2f} seconds")

def count_chunks_in_mariadb(cur):
   print("\nTotal chunks in MariaDB kb_chunks:")
   cur.execute("""
      SELECT COUNT(*) as total_chunks, 
             COUNT(DISTINCT article_id) as unique_articles 
      FROM kb_vector.kb_chunks""")
   for (total_chunks, unique_articles) in cur:
      print(f"Total articles: {unique_articles}")
      print(f"Total chunks: {total_chunks}")

def search_for_closest(text, n, previous=1, next=1):
   print(f"\nSearching for {n} closest chunks to: '{text}'")
   embedding = embed(text)
   closest_chunks = []
   
   query_start = time.time()
   cur.execute("""
      WITH closest_chunks AS (
         SELECT c.chunk_order, c.chunk_content, 
            a.article_id, a.title, a.slug,
            VEC_Distance(c.embedding, Vec_FromText(%s)) as distance
         FROM kb_vector.kb_chunks c
         JOIN kb_vector.kb_articles a ON c.article_id = a.article_id
         ORDER BY distance
         LIMIT %s
      )
      SELECT c2.chunk_order, c2.chunk_content, 
         a.article_id, a.title, a.slug, 
         CASE 
            WHEN c2.chunk_order = cc.chunk_order THEN 'main'
            WHEN c2.chunk_order < cc.chunk_order THEN 'previous'
            ELSE 'next'
         END as chunk_type,
         cc.distance
      FROM closest_chunks cc
      JOIN kb_vector.kb_chunks c2 ON c2.article_id = cc.article_id
      JOIN kb_vector.kb_articles a ON c2.article_id = a.article_id
      WHERE c2.chunk_order BETWEEN (cc.chunk_order - %s) AND (cc.chunk_order + %s)
      ORDER BY cc.distance, c2.article_id, c2.chunk_order
    """, (str(embedding), n, previous, next))
    
   for (chunk_order, chunk_content, article_id, title, slug, chunk_type, distance) in cur:
      closest_chunks.append({
         "article_id": article_id,
         "slug": slug,
         "title": title,
         "chunk_order": chunk_order,
         "chunk_type": chunk_type,
         "chunk_content": chunk_content,
         "distance": distance
        })

   result = f"\nClosest {n} chunks:"
   for chunk in closest_chunks:
      result += f"\n{chunk["distance"]}, {chunk["slug"]}, chunk {chunk["chunk_order"]}, chunk {chunk["chunk_type"]}: {chunk["chunk_content"].replace('\n', ' ')}"
   print(f"{result}")
   query_time = time.time() - query_start
   print(f"Vector search query time: {query_time:.2f} seconds")

   return closest_chunks

def prompt_llm(question, closest_chunks):
   print(f"\n\n\nPrompting LLM with {len(closest_chunks)} chunks and question:\n{question}")
   prompt = f"""
   You are a helpful assistant that answers questions using exclusively the MariaDB Knowledgebase.
   The user asked: {question}
   Use only the following chunks from the MariaDB Knowledgebase to answer the question:
   """
   for chunk in closest_chunks:
      prompt += f"""
      {chunk["chunk_content"]}
      """
   
   response = client.chat.completions.create(
      model="gpt-4o-mini",
      messages=[{"role": "system", "content": prompt}]
   )
   answer = "\n\nReponse from LLM:\n"
   answer += response.choices[0].message.content
   
   sources = "\n\nSources shared to LLM:\n"
   for chunk in closest_chunks:
      sources += f"{chunk["distance"]}, [{chunk["title"]}](https://mariadb.com/kb{chunk["slug"]}, chunk {chunk["chunk_order"]}, {chunk["chunk_content"].replace('\n', ' ')[:20]} ... {chunk["chunk_content"].replace('\n', ' ')[-20:]}\n"
   #print(f"{sources}")

   return f"{answer}{sources}"

# To run MariaDB 11.6 Vector Preview Release with Docker: 
# docker run -p 127.0.0.1:3306:3306  --name mdb_116_vector -e MARIADB_ROOT_PASSWORD=Password123! -d quay.io/mariadb-foundation/mariadb-devel:11.6-vector-preview
# Access MariaDB with:
# docker exec -it mdb_116_vector mariadb --user root -pPassword123!

# For embedding, OpenAI API key is needed. Create at https://platform.openai.com/api-keys and add to system variables with export OPENAI_API_KEY='your-key-here'.
client = OpenAI(
   api_key=os.getenv('OPENAI_API_KEY') 
)

try:
   conn = mariadb.connect(
      host="127.0.0.1",
      port=3306,
      user="root",
      password="Password123!",
      database="kb_vector")
   cur = conn.cursor()

   ## 1. PREPARE TABLES
   delete_database(cur)
   create_tables(cur)
   
   ## Insert KB articles into database
   contents = read_kb_from_slugs()
   insert_content_to_mdb(cur, contents)

   ## Create chunks and embeddings
   items = get_content_from_mdb(cur)
   insert_chunks_and_embedding(items)

   ## 2. EMBED QUESTION AND PROMPT LLM WITH QUESTION AND CLOSEST CHUNKS   

   ## Print amount of articles and chunks in database
   count_chunks_in_mariadb(cur)

   questions = [
      "replication", 
      "create vector index", 
      "where can MariaDB Galera Cluster be downloaded?", 
      "What data types should be used for vector data?"
      ]
   for question in questions:
      closest_chunks = search_for_closest(question, n=5, next=0, previous=0)
      answer = prompt_llm(question, closest_chunks)
      print(answer)

   # Close Connection
   conn.close()

except mariadb.Error as e:
      print(f"Error connecting to the database: {e}")
      sys.exit(1)
