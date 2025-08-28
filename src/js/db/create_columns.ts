import { eq } from "drizzle-orm";
import db from "./db";
import { Fornlamning, fornlamningar, isFornlamningColumn } from "./schema";

const allowedNewCols = [
  "Class",
  "Skadestatus",
  "Placering",
  "Undersökningsstatus",
  "Province",
  "Aktualitetsstatus",
  "Antikvarisk bedömning",
  "Organization",
  "Build Date",
  "Last Changed",
  "URL",
  "Beskrivning",
  "RAÄ-nummer",
  "Lämningsnummer",
  "Terräng",
  "Referens",
  "Orientering",
  "Title",
  "Vegetation",
  "Tradition",
];

const toDbFriendly = (str: string): string =>
  str
    .replace(/å/g, "a")
    .replace(/ä/g, "a")
    .replace(/ö/g, "o")
    .replace(/ /g, "_")
    .toLowerCase();

// get all rows from the database
const rows = await db.select().from(fornlamningar);

const rowsToDelete = [];
rows.forEach((row) => {
  const description = row.description;
  if (!description) {
    rowsToDelete.push(row.inspireid);
    return;
  }

  const newDescriptionEntriesToAdd: Record<string, any> = description
    .split("\n\n")
    .reduce(
      (acc, entry) => {
        const colonIndex = entry.indexOf(":");
        const key = entry.slice(0, colonIndex).trim();
        const value = entry.slice(colonIndex + 1).trim();
        if (allowedNewCols.includes(key)) {
        // @ts-ignore
          acc[toDbFriendly(key)] = value;
        } else {
          acc.rest = acc.rest ? acc.rest + "\n\n" + entry : entry;
        }
        return acc;
      },
      { rest: "" } as Partial<Fornlamning>
    );

    console.log(newDescriptionEntriesToAdd)

  // add new columns to the database. create the column if it doesn't exist
  Object.keys(newDescriptionEntriesToAdd).forEach((key) => {
    if (isFornlamningColumn(key)) {
      db.update(fornlamningar)
        .set({ [key]: newDescriptionEntriesToAdd[key] })
        .where(eq(fornlamningar.inspireid, row.inspireid as string))
        .run();
    } else {
      console.log(`Key ${key} not allowed!`);
    }
  });
});
