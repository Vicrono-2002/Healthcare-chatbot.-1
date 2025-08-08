from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import mysql.connector
from mysql.connector import Error
import bcrypt
from src.helper import download_embeddings
from langchain_pinecone import PineconeVectorStore
from langchain_openai import ChatOpenAI
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv
from src.prompt import *
import os

app = Flask(__name__)
app.secret_key = 'my_secret_key'

load_dotenv()

# Database config
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'healthbot'
}

def get_db_connection():
    try:
        return mysql.connector.connect(**db_config)
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

# Load API keys
os.environ["PINECONE_API_KEY"] = os.environ.get('PINECONE_API_KEY')
os.environ["GEMINI_API_KEY"] = os.environ.get('GEMINI_API_KEY')

# Embeddings and Pinecone retriever
embeddings = download_embeddings()
index_name = "healthcare-chatbot"

docsearch = PineconeVectorStore.from_existing_index(
    index_name=index_name,
    embedding=embeddings
)

retriever = docsearch.as_retriever(search_type="similarity", search_kwargs={"k": 3})

# Chat model (ChatOpenAI)
try:
    llm = ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        model="deepseek/deepseek-r1-0528-qwen3-8b",
        temperature=0.3,
        max_tokens=512,
        openai_api_key=os.environ["GEMINI_API_KEY"]
    )
except Exception as e:
    print(f"Error initializing ChatOpenAI: {e}")
    llm = None

# Prompt and chain setup
prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("human", "{input}")
])

if llm:
    question_answer_chain = create_stuff_documents_chain(llm, prompt)
    rag_chain = create_retrieval_chain(retriever, question_answer_chain)
else:
    rag_chain = None

@app.route('/')
def root():
    if 'user' in session:
        return redirect(url_for('chat_page'))
    return redirect(url_for('login'))

@app.route('/home')
def home():
    return render_template('home.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        connection = get_db_connection()
        if connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            cursor.close()
            connection.close()

            if user and bcrypt.checkpw(password.encode(), user['password'].encode()):
                session['user'] = user['fullname']
                session['user_id'] = user['id']  # Store user ID in session
                return redirect(url_for('chat_page'))
            else:
                flash('Invalid email or password.')
        else:
            flash('Database connection error.')

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        fullname = request.form['fullname']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Passwords do not match.')
            return redirect(url_for('register'))

        hashed_password = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

        connection = get_db_connection()
        if connection:
            try:
                cursor = connection.cursor()
                cursor.execute(
                    "INSERT INTO users (fullname, email, password) VALUES (%s, %s, %s)",
                    (fullname, email, hashed_password.decode())
                )
                connection.commit()
                cursor.close()
                connection.close()
                flash('Registration successful! Please log in.')
                return redirect(url_for('login'))
            except Error as e:
                flash('Error: Email already exists.')
                print(f"Error during registration: {e}")
        else:
            flash('Database connection error.')

    return render_template('register.html')

@app.route('/chat')
def chat_page():
    if 'user' not in session:
        flash('You must be logged in to access the chat.')
        return redirect(url_for('login'))
    return render_template('chat.html')

@app.route("/get", methods=["POST"])
def get_bot_response():
    try:
        user_input = request.form.get("msg")
        print(f"User Input: {user_input}")

        if not rag_chain:
            bot_response = "The AI model is currently unavailable. Please try again later."
        else:
            response = rag_chain.invoke({"input": user_input})
            bot_response = response["answer"]

        print(f"Bot Response: {bot_response}")

        # Save the user's prompt and the bot's response to the database
        if 'user_id' in session:
            user_id = session['user_id']
            connection = get_db_connection()
            if connection:
                try:
                    cursor = connection.cursor()
                    cursor.execute(
                        "INSERT INTO chat_history (user_id, prompt, response) VALUES (%s, %s, %s)",
                        (user_id, user_input, bot_response)
                    )
                    connection.commit()
                except Error as e:
                    print(f"Error saving chat history: {e}")
                finally:
                    cursor.close()
                    connection.close()

        return jsonify({"response": bot_response})

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"response": "An error occurred. Please try again later."})

@app.route('/logout')
def logout():
    if 'user_id' in session:
        user_id = session['user_id']
        connection = get_db_connection()
        if connection:
            try:
                cursor = connection.cursor()
                cursor.execute("DELETE FROM chat_history WHERE user_id = %s", (user_id,))
                connection.commit()
            except Error as e:
                print(f"Error clearing chat history: {e}")
            finally:
                cursor.close()
                connection.close()

    session.pop('user', None)
    session.pop('user_id', None)
    flash('You have been logged out successfully.')
    return redirect(url_for('login'))

@app.route('/get_chat_history', methods=["GET"])
def get_chat_history():
    if 'user_id' not in session:
        return jsonify([])  # Return an empty list if the user is not logged in

    user_id = session['user_id']
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT prompt, response FROM chat_history WHERE user_id = %s ORDER BY created_at ASC",
                (user_id,)
            )
            chat_history = cursor.fetchall()
            return jsonify(chat_history)
        except Error as e:
            print(f"Error fetching chat history: {e}")
            return jsonify([])
        finally:
            cursor.close()
            connection.close()

    return jsonify([])

if __name__ == "__main__":
    app.run(debug=True)