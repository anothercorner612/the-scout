# Project: Global Creative-Tech Job Hunter

## Tools
- Use **Gemini 2.5 Flash** for high-volume job description scoring (low latency) and  with Grounding** for "Hiring Manager" discovery and company research.

## The Hunting Loop
1. **Discover:** Search Greenhouse, Lever, and Ashby using Google Search Grounding for roles matching `goals.md`.
2. **Verify:** Use Gemini's multimodal capabilities to "read" the job page and extract the Hiring Manager's name/title.
3. **Draft:** Create a 150-word "Vibe Check" email for each role that mentions a specific recent company achievement.

## Tracking
- Store everything in `job_tracker.db`. 
- Statuses: [Unexplored, Researched, Applied, Followed-Up]
