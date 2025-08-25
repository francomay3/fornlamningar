import { sqliteTable, text, real, integer } from 'drizzle-orm/sqlite-core';
import { InferSelectModel, InferInsertModel } from 'drizzle-orm';

export const fornlamningar = sqliteTable('fornlamningar', {
  inspireid: text('inspireid'),
  sitename: text('sitename'),
  uuid: text('uuid'),
  longitude: real('longitude'),
  latitude: real('latitude'),
  description: text('description'),
  generatedDescription: text('generatedDescription'),
  visibility: integer('visibility'),
  quality: integer('quality'),
});

export type Fornlamning = InferSelectModel<typeof fornlamningar>;
export type NewFornlamning = InferInsertModel<typeof fornlamningar>;
