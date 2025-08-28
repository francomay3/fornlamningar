// get a random sample of 4 rows of the DB
import { eq, sql } from 'drizzle-orm';
import db from './db.js';
import { fornlamningar } from './schema.js';
import getGeneratedDescription from './getGeneratedDescription.js';
import pLimit from 'p-limit';

const MAX_CONCURRENT_GENERATIONS = 4;
const DB_BATCH_SIZE = 500;

const timeLogUtil = (time: number) => {
 if (time < 1000) {
  return `${time}ms`;
 } else if (time < 60000) {
  return `${time / 1000}s`;
 } else if (time < 3600000) {
  return `${time / 60000}m`;
 } else {
  const hours = Math.floor(time / 3600000);
  const minutes = Math.floor((time % 3600000) / 60000);
  return `${hours}h ${minutes}m`;
 }
}

async function getRandomSample() {
  try {
    const result = await db.select()
      .from(fornlamningar)
      .where(
        sql`${fornlamningar.location} = 'Visible above ground' AND 
            ${fornlamningar.generatedDescription} IS NULL`
      )
      .orderBy(sql`RANDOM()`)
      .limit(DB_BATCH_SIZE);
      
    
    const limit = pLimit(MAX_CONCURRENT_GENERATIONS); // max 4 concurrent operations

    console.log(`Starting processing with max ${MAX_CONCURRENT_GENERATIONS} concurrent operations...`);
    const startTime = Date.now();

    const promises = result.map((row, i) => 
      limit(async () => {
        console.log(`Generating description for ${row.inspireid} (${i+1} of ${result.length})`);
        const generatedResult = await getGeneratedDescription(row);

        return db.update(fornlamningar).set({
          generatedDescription: generatedResult
        }).where(eq(fornlamningar.inspireid, row.inspireid as string));
      })
    );

    await Promise.all(promises);
    
    const totalTime = Date.now() - startTime;
    console.log(`🎉 All generations completed in ${timeLogUtil(totalTime)}`);

  } catch (error) {
    console.error('Error fetching random sample:', error);
    return [];
  }
}

getRandomSample().catch(console.error);