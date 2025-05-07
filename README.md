# Central Memory Hub

A sophisticated Central Memory Hub using Python, Flask, PostgreSQL, and Pinecone to store, manage, and search structured and unstructured data via embeddings. Enhanced with multi-agent communication and knowledge management capabilities.

## Features

- PostgreSQL database with advanced data models
- OpenAI integration for generating embeddings
- Pinecone Vector Database for storing and searching embeddings
- Comprehensive REST API with authentication
- Multi-agent session and communication tracking
- Knowledge indexing and decision logging
- Organizational state management
- Experimental tracking for agent learning
- User insights for behavior analysis
- Memory linking between structured and vector data
- User-friendly web interface for managing data
- Enhanced security features with API key management

## Security Features

The system implements multiple layers of security to protect data and prevent unauthorized access:

- **API Key Management System**:
  - Create, view, and revoke API keys with custom permissions
  - Set individual rate limits per API key
  - Track API key usage and request logs
  - Time-based expiration options

- **Rate Limiting**:
  - Thread-safe implementation to prevent abuse
  - Customizable limits per endpoint and API key
  - Automatic request throttling

- **Input Validation**:
  - Comprehensive schema-based validation
  - Protection against malformed data
  - Type checking and constraint enforcement

- **Cross-Site Request Forgery (CSRF) Protection**:
  - Token-based CSRF prevention
  - Form and AJAX request protection

- **Cross-Site Scripting (XSS) Prevention**:
  - HTML content sanitization
  - Output encoding
  - User input filtering

- **Content Security Policy (CSP)**:
  - Strict CSP headers to prevent script injection
  - Resource restriction to trusted sources

- **Request Logging and Auditing**:
  - Detailed logging of all API access
  - IP address and user agent tracking
  - Request timestamps and response status

## Database Migration

The system has been migrated from SQLite to PostgreSQL for improved scalability, performance, and advanced data type support. The migration includes:

- Preservation of all existing data from the original SQLite database
- Enhanced schema with JSONB fields for flexible data storage
- Proper indexing strategies for performance optimization
- Foreign key relationships between related data models
- UUID-based identifiers for all tables

## Multi-Agent Communication Architecture

The system now includes comprehensive support for multi-agent orchestration:

### Agent Directory (AI Org Chart)
Maintain a structured organization of AI agents and their relationships:
- Hierarchical organization with reporting structures
- Agent capabilities and roles tracking
- Seniority levels and status management
- Visualize organization chart in list or tree view

### Agent Sessions
Track when and what each agent does during interactions:
- Session management with start/end timestamps
- Current focus tracking
- Context tagging for organized memory access

### Message Logging
Record all inter-agent and agent-user communications:
- Structured message types (instruction, status_update, handoff, question)
- Complete conversation history within sessions
- Sender/receiver relationships

### Knowledge Management
- Term indexing with relevance scoring
- Source tracking for knowledge provenance
- Synonym management for flexible retrieval

### Decision Tracking
- Log all agent decisions with impact assessment
- Context preservation for decision traceability
- Reversal possibility tracking

## API Usage

The Memory Hub provides a comprehensive RESTful API that can be accessed using the OpenAPI schema. This can be used with Custom GPTs or other applications to interact with the Memory Hub and support multi-agent workflows.

## Deployment

### Reserved VM Deployment

For production use, the Central Memory Hub is designed to be deployed as a Web Server on a Reserved VM instance:

1. **Environment Requirements:**
   - Python 3.11+
   - PostgreSQL database
   - Required API keys:
     - OpenAI API key (`OPENAI_API_KEY`)
     - Pinecone API key (`PINECONE_API_KEY`)
     - Custom API key for authentication (`API_KEY`)
     - Session secret for security (`SESSION_SECRET`)

2. **Deployment Steps:**
   - Choose "Web Server" as the app type (not Background Worker)
   - Set the environment variables listed above
   - The application server runs with Gunicorn on port 5000
   - Use `main.py` as the entry point
   - For custom domain setup, update the URL in the OpenAPI schema

3. **Database Configuration:**
   - The application will automatically connect to the provided PostgreSQL database
   - Tables are created automatically if they don't exist
   - Access the database using environment variables: DATABASE_URL, PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE

4. **Post-Deployment Verification:**
   - Visit `https://memory-vault-angelson.replit.app/admin/settings` to configure the application
   - Test API endpoints using the `https://memory-vault-angelson.replit.app/api-keys` interface to create and manage API keys
   - Verify Pinecone connectivity by adding and searching unstructured data

For detailed logging information, view the application logs in the Replit console.

## OpenAPI Schema for Custom GPT Integration

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "Central Memory Hub API",
    "description": "API for managing structured and unstructured data with vector embeddings in a Central Memory Hub",
    "version": "1.0.0"
  },
  "servers": [
    {
      "url": "https://memory-vault-angelson.replit.app",
      "description": "Production server"
    },
    {
      "url": "https://a4bcd18d-c239-4cf3-b41c-6f743ef6fa20-00-32na6d6s4kheq.kirk.replit.dev",
      "description": "Development server"
    }
  ],
  "security": [
    {
      "ApiKeyAuth": []
    }
  ],
  "paths": {
    "/memory/unstructured": {
      "post": {
        "description": "Add unstructured memory to the Central Memory Hub",
        "operationId": "addUnstructuredMemory",
        "security": [
          {
            "ApiKeyAuth": []
          }
        ],
        "requestBody": {
          "description": "Content to add to unstructured memory",
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "content": {
                    "type": "string",
                    "description": "The content to store in memory"
                  }
                },
                "required": ["content"]
              }
            }
          }
        },
        "responses": {
          "201": {
            "description": "Unstructured memory added successfully",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "id": {
                      "type": "string",
                      "description": "The unique identifier for the memory"
                    },
                    "pinecone_id": {
                      "type": "string",
                      "description": "The ID of the vector in Pinecone"
                    },
                    "message": {
                      "type": "string",
                      "description": "Status message"
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "Bad Request - Missing required fields"
          },
          "401": {
            "description": "Unauthorized - Invalid or missing API key"
          },
          "500": {
            "description": "Internal Server Error"
          }
        }
      }
    },
    "/memory/unstructured/{id}": {
      "get": {
        "description": "Retrieve unstructured memory by ID",
        "operationId": "getUnstructuredMemory",
        "security": [
          {
            "ApiKeyAuth": []
          }
        ],
        "parameters": [
          {
            "name": "id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "ID of the memory to retrieve"
          }
        ],
        "responses": {
          "200": {
            "description": "Successfully retrieved memory",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "id": {
                      "type": "string"
                    },
                    "content": {
                      "type": "string"
                    },
                    "pinecone_id": {
                      "type": "string"
                    }
                  }
                }
              }
            }
          },
          "401": {
            "description": "Unauthorized - Invalid or missing API key"
          },
          "404": {
            "description": "Memory not found"
          },
          "500": {
            "description": "Internal Server Error"
          }
        }
      }
    },
    "/search": {
      "post": {
        "description": "Search unstructured data using semantic similarity",
        "operationId": "searchMemory",
        "security": [
          {
            "ApiKeyAuth": []
          }
        ],
        "requestBody": {
          "description": "Search query",
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "query": {
                    "type": "string",
                    "description": "The search query"
                  }
                },
                "required": ["query"]
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Search results",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "query": {
                      "type": "string",
                      "description": "The original query"
                    },
                    "results": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "id": {
                            "type": "string"
                          },
                          "content": {
                            "type": "string"
                          },
                          "pinecone_id": {
                            "type": "string"
                          },
                          "similarity_score": {
                            "type": "number",
                            "format": "float"
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "Bad Request - Missing query"
          },
          "401": {
            "description": "Unauthorized - Invalid or missing API key"
          },
          "500": {
            "description": "Internal Server Error"
          }
        }
      }
    },
    "/memory/structured": {
      "post": {
        "description": "Add structured memory to the Central Memory Hub",
        "operationId": "addStructuredMemory",
        "security": [
          {
            "ApiKeyAuth": []
          }
        ],
        "requestBody": {
          "description": "Structured memory data",
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "gpt_role": {
                    "type": "string",
                    "description": "The role or persona of the GPT creating this memory"
                  },
                  "decision_text": {
                    "type": "string",
                    "description": "The text of the decision or information being stored"
                  },
                  "context_embedding": {
                    "type": "array",
                    "items": {
                      "type": "number",
                      "format": "float"
                    },
                    "description": "Vector embedding of the context"
                  },
                  "related_documents": {
                    "type": "array",
                    "items": {
                      "type": "string"
                    },
                    "description": "List of related document IDs"
                  }
                },
                "required": ["gpt_role", "decision_text", "context_embedding", "related_documents"]
              }
            }
          }
        },
        "responses": {
          "201": {
            "description": "Structured memory added successfully",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "id": {
                      "type": "string"
                    },
                    "message": {
                      "type": "string"
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "Bad Request - Missing required fields"
          },
          "401": {
            "description": "Unauthorized - Invalid or missing API key"
          },
          "500": {
            "description": "Internal Server Error"
          }
        }
      }
    },
    "/memory/structured/{id}": {
      "get": {
        "description": "Retrieve structured memory by ID",
        "operationId": "getStructuredMemory",
        "security": [
          {
            "ApiKeyAuth": []
          }
        ],
        "parameters": [
          {
            "name": "id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "ID of the structured memory to retrieve"
          }
        ],
        "responses": {
          "200": {
            "description": "Successfully retrieved structured memory",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "id": {
                      "type": "string"
                    },
                    "gpt_role": {
                      "type": "string"
                    },
                    "decision_text": {
                      "type": "string"
                    },
                    "context_embedding": {
                      "type": "array",
                      "items": {
                        "type": "number",
                        "format": "float"
                      }
                    },
                    "related_documents": {
                      "type": "array",
                      "items": {
                        "type": "string"
                      }
                    },
                    "timestamp": {
                      "type": "string"
                    }
                  }
                }
              }
            }
          },
          "401": {
            "description": "Unauthorized - Invalid or missing API key"
          },
          "404": {
            "description": "Structured memory not found"
          },
          "500": {
            "description": "Internal Server Error"
          }
        }
      }
    },
    "/context": {
      "post": {
        "description": "Add a shared context entry",
        "operationId": "addSharedContext",
        "security": [
          {
            "ApiKeyAuth": []
          }
        ],
        "requestBody": {
          "description": "Shared context data",
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "sender": {
                    "type": "string",
                    "description": "The sender of the context"
                  },
                  "recipients": {
                    "type": "array",
                    "items": {
                      "type": "string"
                    },
                    "description": "List of recipients for the context"
                  },
                  "context_tag": {
                    "type": "string",
                    "description": "Tag describing the context"
                  },
                  "memory_refs": {
                    "type": "array",
                    "items": {
                      "type": "string"
                    },
                    "description": "References to memory IDs"
                  }
                },
                "required": ["sender", "recipients", "context_tag", "memory_refs"]
              }
            }
          }
        },
        "responses": {
          "201": {
            "description": "Shared context added successfully",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "id": {
                      "type": "string"
                    },
                    "message": {
                      "type": "string"
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "Bad Request - Missing required fields"
          },
          "401": {
            "description": "Unauthorized - Invalid or missing API key"
          },
          "500": {
            "description": "Internal Server Error"
          }
        }
      },
      "get": {
        "description": "Get all shared context entries",
        "operationId": "getAllContexts",
        "security": [
          {
            "ApiKeyAuth": []
          }
        ],
        "responses": {
          "200": {
            "description": "Successfully retrieved all shared contexts",
            "content": {
              "application/json": {
                "schema": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "id": {
                        "type": "string"
                      },
                      "sender": {
                        "type": "string"
                      },
                      "recipients": {
                        "type": "array",
                        "items": {
                          "type": "string"
                        }
                      },
                      "context_tag": {
                        "type": "string"
                      },
                      "memory_refs": {
                        "type": "array",
                        "items": {
                          "type": "string"
                        }
                      },
                      "timestamp": {
                        "type": "string"
                      }
                    }
                  }
                }
              }
            }
          },
          "401": {
            "description": "Unauthorized - Invalid or missing API key"
          },
          "500": {
            "description": "Internal Server Error"
          }
        }
      }
    }
  },
  "components": {
    "schemas": {
      "UnstructuredMemory": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "Unique identifier for the memory"
          },
          "content": {
            "type": "string",
            "description": "Content of the memory"
          },
          "pinecone_id": {
            "type": "string",
            "description": "ID of the vector in Pinecone"
          }
        }
      },
      "StructuredMemory": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "Unique identifier for the memory"
          },
          "gpt_role": {
            "type": "string",
            "description": "Role of the GPT creating this memory"
          },
          "decision_text": {
            "type": "string",
            "description": "Content of the decision"
          },
          "context_embedding": {
            "type": "array",
            "items": {
              "type": "number",
              "format": "float"
            },
            "description": "Vector embedding of the context"
          },
          "related_documents": {
            "type": "array",
            "items": {
              "type": "string"
            },
            "description": "List of related document IDs"
          },
          "timestamp": {
            "type": "string",
            "description": "Timestamp when the memory was created"
          }
        }
      },
      "SharedContext": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "Unique identifier for the context"
          },
          "sender": {
            "type": "string",
            "description": "Sender of the context"
          },
          "recipients": {
            "type": "array",
            "items": {
              "type": "string"
            },
            "description": "List of recipients"
          },
          "context_tag": {
            "type": "string",
            "description": "Tag describing the context"
          },
          "memory_refs": {
            "type": "array",
            "items": {
              "type": "string"
            },
            "description": "References to memory IDs"
          },
          "timestamp": {
            "type": "string",
            "description": "Timestamp when the context was created"
          }
        }
      },
      "Error": {
        "type": "object",
        "properties": {
          "error": {
            "type": "string",
            "description": "Error message"
          }
        }
      }
    },
    "securitySchemes": {
      "ApiKeyAuth": {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-KEY"
      }
    }
  }
}
```

## Usage with Custom GPT

To use this API with a Custom GPT:

1. Deploy your Memory Hub application to Replit
2. The schema is configured to use the URL: `https://a4bcd18d-c239-4cf3-b41c-6f743ef6fa20-00-32na6d6s4kheq.kirk.replit.dev` - make sure this is the correct URL for your deployment
3. Configure your Custom GPT to use this OpenAPI schema
4. Make sure to provide your API key in the X-API-KEY header for all requests

## Example Usage

### Adding Unstructured Memory

```json
POST /memory/unstructured
Headers: X-API-KEY: your_api_key
{
  "content": "The meeting is scheduled for April 15th at 2 PM. Topics to be discussed include project timeline and resource allocation."
}
```

### Searching Memory

```json
POST /search
Headers: X-API-KEY: your_api_key
{
  "query": "When is the meeting scheduled?"
}
```

### Adding Structured Memory

```json
POST /memory/structured
Headers: X-API-KEY: your_api_key
{
  "gpt_role": "project_manager",
  "decision_text": "Decided to extend the project deadline by two weeks due to unexpected technical challenges.",
  "context_embedding": [0.1, 0.2, 0.3, ...],
  "related_documents": ["doc123", "doc456"]
}
```

### Creating Shared Context

```json
POST /context
Headers: X-API-KEY: your_api_key
{
  "sender": "team_lead",
  "recipients": ["developer1", "developer2"],
  "context_tag": "project_update",
  "memory_refs": ["mem123", "mem456"]
}
```