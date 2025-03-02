/**
 * NexusAI JavaScript Client
 * A simple client for interacting with the NexusAI Forge API.
 */
class NexusAIClient {
  /**
   * Initialize the NexusAI client.
   * @param {string} apiKey - Your NexusAI API key
   * @param {string} baseUrl - The base URL of the NexusAI API
   */
  constructor(apiKey, baseUrl = 'http://localhost:8000/api/v1') {
    this.apiKey = apiKey;
    this.baseUrl = baseUrl;
    this.headers = {
      'X-API-Key': apiKey,
      'Content-Type': 'application/json'
    };
  }

  /**
   * Get a list of available models.
   * @returns {Promise<Array>} A promise that resolves to an array of models
   */
  async listModels() {
    const url = `${this.baseUrl}/models`;
    const response = await fetch(url, {
      method: 'GET',
      headers: this.headers
    });
    
    if (!response.ok) {
      throw new Error(`HTTP error! Status: ${response.status}`);
    }
    
    return await response.json();
  }

  /**
   * Generate text using a specified model.
   * @param {string} modelId - The ID of the model to use
   * @param {string} prompt - The prompt to generate text from
   * @param {number} maxTokens - Maximum number of tokens to generate
   * @param {number} temperature - Sampling temperature (0.0-1.0)
   * @returns {Promise<Object>} A promise that resolves to the model's response
   */
  async generateText(modelId, prompt, maxTokens = 50, temperature = 0.7) {
    const url = `${this.baseUrl}/models/${modelId}/generate`;
    const payload = {
      prompt,
      max_tokens: maxTokens,
      temperature
    };
    
    const response = await fetch(url, {
      method: 'POST',
      headers: this.headers,
      body: JSON.stringify(payload)
    });
    
    if (!response.ok) {
      throw new Error(`HTTP error! Status: ${response.status}`);
    }
    
    return await response.json();
  }

  /**
   * Get usage statistics for your API key.
   * @returns {Promise<Object>} A promise that resolves to usage statistics
   */
  async getUsage() {
    const url = `${this.baseUrl}/usage`;
    const response = await fetch(url, {
      method: 'GET',
      headers: this.headers
    });
    
    if (!response.ok) {
      throw new Error(`HTTP error! Status: ${response.status}`);
    }
    
    return await response.json();
  }
}

// Example usage (for Node.js, use with 'node javascript_client.js')
// For browser use, wrap in a function or event listener
async function runExample() {
  // Replace with your actual API key
  const API_KEY = 'your_api_key_here';
  
  // Initialize the client
  const client = new NexusAIClient(API_KEY);
  
  try {
    // List available models
    console.log('Available models:');
    const models = await client.listModels();
    models.forEach(model => {
      console.log(`- ${model.name} (ID: ${model.id}): ${model.description}`);
    });
    
    // Choose the first model from the list
    if (models.length > 0) {
      const modelId = models[0].id;
      
      // Generate text
      console.log('\nGenerating text...');
      const response = await client.generateText(
        modelId,
        'Write a short poem about artificial intelligence.',
        100
      );
      
      console.log('\nGenerated text:');
      response.choices.forEach(choice => {
        console.log(choice.text);
      });
      
      console.log('\nUsage:');
      console.log(`Prompt tokens: ${response.usage.prompt_tokens}`);
      console.log(`Completion tokens: ${response.usage.completion_tokens}`);
      console.log(`Total tokens: ${response.usage.total_tokens}`);
      
      // Get usage statistics
      // Wait a moment for usage to be recorded
      await new Promise(resolve => setTimeout(resolve, 1000));
      console.log('\nAPI Key usage statistics:');
      const usage = await client.getUsage();
      console.log(JSON.stringify(usage, null, 2));
    }
  } catch (error) {
    console.error(`Error: ${error.message}`);
  }
}

// For Node.js
if (typeof window === 'undefined') {
  // Using require for Node.js fetch (Node.js v18+ has built-in fetch)
  if (!globalThis.fetch) {
    console.log('This example requires Node.js v18+ or the node-fetch package.');
    console.log('For older Node.js versions, install node-fetch and uncomment the line below:');
    console.log('// globalThis.fetch = require("node-fetch");');
  } else {
    runExample();
  }
}

// Export for browser use
if (typeof window !== 'undefined') {
  window.NexusAIClient = NexusAIClient;
}

// Export for module use
if (typeof module !== 'undefined') {
  module.exports = NexusAIClient;
}
