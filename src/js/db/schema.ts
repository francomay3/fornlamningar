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

    // ── new parsed fields (all TEXT) ──
    class: text('class'),
    damage_status: text('damage_status'),
    location: text('location'),
    investigation_status: text('investigation_status'),
    province: text('province'),
    current_status: text('current_status'),
    heritage_assessment: text('heritage_assessment'),
    organization: text('organization'),
    build_date: text('build_date'),
    last_changed: text('last_changed'),
    url: text('url'),
    description_swedish: text('description_swedish'),
    raa_number: text('raa_number'),
    site_number: text('site_number'),
    terrain: text('terrain'),
    reference: text('reference'),
    orientation: text('orientation'),
    title: text('title'),
    vegetation: text('vegetation'),
    tradition: text('tradition'),
    rest: text('rest'),
});

export type Fornlamning = InferSelectModel<typeof fornlamningar>;
export type NewFornlamning = InferInsertModel<typeof fornlamningar>;

export const isFornlamningColumn = (key: string): key is keyof Fornlamning => Object.keys(fornlamningar).includes(key)
