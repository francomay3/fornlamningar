import { drizzle } from 'drizzle-orm/better-sqlite3';
import Database from 'better-sqlite3';

const db_filename = "fornlamningar_filtered_20km.sqlite";
const dbPath = `./src/data/${db_filename}`;

console.log('Connecting to database:', dbPath);

// Initialize database and ORM
const sqlite = new Database(dbPath);
const db = drizzle(sqlite);

export default db;