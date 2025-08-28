import ollama from "./ollama_util";
import { Fornlamning } from "./schema";

const getGeneratedDescription = async (row: Fornlamning): Promise<string> => {
  if (!row.description) {
    return "empty description";
  }
  const instructions = 
`Write a short and neutral description in English (1-2 sentences) about an archaeological site.
Use simple, factual language that is accessible to visitors.
Focus on the most relevant and interesting details, such as the type of site, approximate age, location, and any unique features.
Avoid emotional, dramatic, or promotional language.
Do not include any headers, introductions, URLs, or extra commentary. Return only the description.
`;

    const data =
`class: ${row.class},
description: ${row.description},
vegetation: ${row.vegetation},
tradition: ${row.tradition},
damage_status: ${row.damage_status},
location: ${row.location},
`;

  const description = await ollama(
    data,
    instructions,
  );

  // if there is a \n\n, remove everything after it. if it starts with a \n, remove it. if there is \n#, remove everything after it.
  return description.replace(/\n\n.*/, '').replace(/^\n/, '').replace(/\n#.*/, '');
};

export default getGeneratedDescription;
