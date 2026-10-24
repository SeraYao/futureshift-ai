### RunPod

RunPod Serverless was used to deploy and invoke the
Qwen/Qwen3-8B large language model through an
OpenAI-compatible API endpoint.

The integration supports AI-assisted CV information
extraction, allowing users to extract relevant career
and skill information from uploaded resumes.

The RunPod API was successfully invoked and tested
using synthetic CV data.

The application includes configurable API timeouts
to accommodate serverless GPU cold starts.

For privacy and security, API credentials are stored
as environment variables rather than committed
to the public GitHub repository.

The core career recommendation system remains
functional without the optional AI extraction service.
