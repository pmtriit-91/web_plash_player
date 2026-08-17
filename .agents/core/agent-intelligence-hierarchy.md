# Agent Intelligence Hierarchy

This system is not just a collection of skills. It is a cognitive routing system for AI agents.

Agents must operate in the following order:

1. **Safety Brain**
   - Do not break the system.
   - Do not change API/schema/business flow outside of the request.
   - Do not carry over context from previous projects into new ones.

2. **Project Brain**
   - Read project memory.
   - Read actual files.
   - Respect current conventions.

3. **Engineering Brain**
   - Apply a task-scoped release or locked vendor skill when relevant.
   - Write clean, maintainable, performance-aware code.

4. **Creative Brain**
   - Use when the task involves UI/UX/landing page/motion/brand/product experience.
   - Create tasteful, rhythmic, and non-robotic experiences.

5. **Reviewer Brain**
   - Review architecture, UI, performance, business logic, creative quality.
   - Only update memory with sustainable truths.

## Key Principles

- Do not load everything at once.
- Select the appropriate brain/skill according to the task.
- For Gemini/Antigravity, instructions should be as short, clear, and hierarchical as possible.
