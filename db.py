import mysql.connector
from mysql.connector import Error
from config import Config


def get_db_connection():
    try:
        connection = mysql.connector.connect(**Config.DB_CONFIG)
        return connection
    except Error as e:
        print("Database connection failed:", e)
        return None