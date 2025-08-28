const ollama = async (data: string, instruction: string) =>{
    const baseUrl = "http://localhost:11434";
    const prompt = `
    SOURCE DATA:
    ${data}

    YOUR INSTRUCTIONS:
    ${instruction}
    `;

    const response = await fetch(`${baseUrl}/api/generate`, {
        method: "POST",
        body: JSON.stringify({
            model: "phi3",
            prompt,
            stream: false,
        }),
    });

    const responseData = await response.json();
    return responseData.response;
}

export default ollama;