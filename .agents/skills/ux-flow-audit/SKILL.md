---
name: ux-flow-audit
description: Guides systematic UX flow audits using Nielsen's 10 usability heuristics and cognitive load analysis. Use whenever someone asks about UX review, usability audit, flow analysis, user experience issues, confusion in their app, navigation problems, cognitive load, onboarding friction, or wants a second opinion on an interface or workflow — even if they don't say "UX audit." Also use when someone describes a complex multi-step process they're building and you can proactively suggest UX improvements. This skill walks through a structured conversation to identify friction points and suggest improvements, and works for web apps, mobile apps, desktop software, or any digital product.
---

# UX Flow Audit

## Overview

This skill guides you through a structured yet conversational UX audit of any digital product — web app, mobile app, desktop software, or even a complex workflow that exists only in description. The goal is to identify friction points, reduce cognitive effort, and suggest concrete improvements.

The approach combines **Nielsen's 10 usability heuristics** with **cognitive load analysis**, applied through a natural conversation with the user. You don't produce a rigid template report; instead, you think out loud, ask questions, and help the user see their own product with fresh eyes.

## When to Use This Skill

Use this skill whenever someone asks you to:

- Review their app's UX or usability
- Audit a specific flow (onboarding, checkout, settings, search, etc.)
- Find out why users get confused or lost
- Reduce the learning curve for a complex feature
- Give a "second opinion" on an interface they built
- Analyze cognitive load or mental effort in a workflow
- Improve navigation, information architecture, or task completion
- Review a codebase for UX issues (routing, component structure, state management patterns that affect the user experience)

The skill is triggered by conversational cues like: "Can you look at my app?", "This doesn't feel right", "Users keep getting stuck on X", "How can I make this less confusing?", "I'm redesigning X flow." Even if the user frames it as a code review or feature request, if UX is involved, use this skill.

## Core Principles

### 1. Empathy First

Before identifying problems, understand who the user is and what they're trying to accomplish. Every design decision makes sense to someone. Start by understanding the context, then evaluate. Ask questions like:

- "Who is the primary user of this flow?"
- "What is the single most important thing they need to accomplish?"
- "How technically savvy are they?"
- "How often will they do this task? (daily, weekly, once ever)"

### 2. Find the Friction, Not Just the Flaws

Not every heuristic violation is a real problem. A hamburger menu on a content site might be fine; on a complex SaaS dashboard it might be deadly. Focus on what actually creates friction for the real user.

### 3. Prioritize

Not all issues are equal. Use a conversational severity scale:
- **Critical** — blocks task completion entirely
- **Major** — significantly slows or frustrates the user
- **Minor** — cosmetic annoyance or edge case
- **Nitpick** — polish, nice-to-have

### 4. Suggest, Don't Prescribe

The user knows their product better than you do. Offer options and explain the tradeoffs. "You could move the save button here, which would make it more visible, but it might crowd the delete action. What do you think?"

## The Framework: Nielsen's 10 Usability Heuristics

These are your lens. During the conversation, mentally map what you see against these heuristics. Don't checklist them mechanically — let them guide your attention.

### 1. Visibility of System Status
Users should always know what's happening. Look for:
- Loading states that don't explain what's loading (spinners without context)
- Long operations without progress indication
- Actions that happen silently (saved? submitted? sent? the user can't tell)
- Navigation that doesn't show where the user currently is
- Multi-step processes without step indicators

**Conversational opener**: "When the user clicks 'Save,' do they know it actually saved? What feedback do they get?"

### 2. Match Between System and Real World
The system should speak the user's language. Look for:
- Jargon, technical terms, or internal company language used in UI copy
- Metaphors that don't match the user's mental model (e.g., "library" when users think "folder")
- Icons that require cultural knowledge or domain expertise
- Date formats, number formats, or units that don't match the user's locale

**Conversational opener**: "Who's the audience for this? Would they use the same terminology you're using in these labels?"

### 3. User Control and Freedom
Users need an "emergency exit." Look for:
- No undo or confirmation on destructive actions
- No "back" or "cancel" on multi-step flows
- Forms that lose all input if you navigate away
- Modals that can't be dismissed with Escape or clicking outside
- Operations that can't be interrupted (no pause, no cancel)

**Conversational opener**: "What happens if someone clicks this by accident? Can they undo it?"

### 4. Consistency and Standards
Same words, same actions, same things mean the same way everywhere. Look for:
- Different terminology for the same concept in different screens
- Different visual treatment for the same type of action (e.g., three different button styles for "save")
- Inconsistent placement of common elements (search bar moves between pages)
- Custom UI patterns where standard browser/platform conventions would work
- The same action triggered differently in different places (click vs drag vs menu)

**Conversational opener**: "Is 'Delete' always called 'Delete' everywhere, or do some screens say 'Remove' or 'Archive'?"

### 5. Error Prevention
Better than good error messages is preventing errors. Look for:
- Destructive actions without confirmation
- No input validation until submission (why let me type an invalid email?)
- No constraints on inputs (date fields that accept any string, quantity fields that accept negative numbers)
- Missing or confusing defaults

**Conversational opener**: "What kinds of mistakes do users make here? Could the interface prevent those?"

### 6. Recognition Rather Than Recall
Minimize the user's memory load. Look for:
- Information that's on one screen but needed on another without being carried forward
- Multiple steps where the user must remember previous choices
- Hidden navigation or actions behind hover states
- No search or filter in long lists
- Fields that require users to remember information from another source (look up account number, recall a code)

**Conversational opener**: "How much does the user need to remember between steps? Could any of that information be shown to them instead of requiring them to recall it?"

### 7. Flexibility and Efficiency of Use
Experienced users should be able to move faster. Look for:
- No keyboard shortcuts for power users
- No bulk actions (edit one item at a time when there are many)
- No personalization or customization
- Repetitive tasks that require the same clicks every time
- No way to skip or accelerate common paths

**Conversational opener**: "How would a power user do this 50 times in a row? Are there any shortcuts or bulk operations?"

### 8. Aesthetic and Minimalist Design
Don't show what users don't need. Look for:
- Cluttered screens with too many options
- Information that's rarely needed by anyone but shown to everyone
- Redundant information displayed in multiple places
- Overly ornate visual elements that don't serve the task
- Too many calls to action on the same screen

**Conversational opener**: "If you had to remove half of what's on this screen, what would you keep? What would you cut?"

### 9. Help Users Recognize, Diagnose, and Recover from Errors
Error messages should be helpful, not cryptic. Look for:
- Generic error messages ("Error occurred", "Something went wrong")
- Technical error codes without explanation
- No guidance on how to fix the problem
- Red border on a field without telling you what's wrong
- Error messages that disappear too quickly (toast notifications)
- Validation errors shown only on submit instead of inline

**Conversational opener**: "When something goes wrong, does the user know exactly what happened and how to fix it? Or do they have to guess?"

### 10. Help and Documentation
The best system doesn't need documentation, but when it does, help should be findable. Look for:
- No contextual help for complex features
- Help content that's generic or outdated
- Documentation that describes features instead of solving user problems
- No tooltips, microcopy, or inline guidance for unfamiliar concepts
- The user has to leave the app to get help

**Conversational opener**: "Where would a new user go to learn how to do this? Is the help in the flow or do they have to hunt for it?"

## Cognitive Load Analysis

Beyond the heuristics, specifically assess how much mental effort the flow requires. This is what makes users tired and makes complex apps hard to learn.

### Types of Cognitive Load

**Intrinsic load** — unavoidable complexity of the task itself.
- Can you simplify the task rather than the interface? (e.g., do they really need to configure all 12 options, or could you pick smart defaults?)
- Can you break one complex task into several simpler ones?
- Can you defer advanced features so beginners aren't overwhelmed?

**Extraneous load** — unnecessary mental effort caused by poor design.
- Is the user searching for information that should be visible?
- Are they switching between unrelated modes or contexts?
- Do they need to hold information in memory between steps?
- Are they deciphering unclear labels, icons, or instructions?
- Do related actions require navigating to different screens?

**Germane load** — effort spent on learning and pattern-building.
- Does the design help users build accurate mental models?
- Are interactions consistent so learning transfers?
- Are new concepts introduced with examples or analogies?

### Cognitive Load Signals

Watch for these in the user's description of their own app:
- "Users have to go back and forth between two screens"
- "I get support tickets asking 'how do I find X'"
- "Power users love it but new users can't figure it out"
- "The settings page has too many options"
- "The onboarding takes 15 minutes"

### The 3-Click / 3-Tap Sanity Check

For any flow you're reviewing:
- Can the user reach their primary goal in 3 actions or fewer?
- If not, does the user understand why each added step exists?
- Is each step clearly scoped to one decision or action?

## The Audit Conversation

This is how you structure the dialogue. Don't follow it like a script — adapt to what the user tells you.

### Phase 1: Context

Start by understanding what you're looking at.

```
You: "Tell me about the app and what you want me to look at."
User: "It's a project management tool. The task creation flow feels clunky."
You: "Who uses this? Daily project managers? Occasional contributors? Both?"
User: "Both. PMs use it every day, devs use it once a sprint."
You: "OK, so we need to serve both a frequent power user and an occasional user. Let's start with..."
```

Key questions to ask:
- Who are the users and how often do they use this?
- What's the primary goal of the flow you're describing?
- What bugs or confusions have you observed?
- Do you have any analytics data (drop-off rates, time-on-task)?

### Phase 2: Walk the Flow

Guide the user through the flow step by step. Read the code if the user provides a codebase; otherwise ask them to describe the screens.

For each step, ask:
- "What does the user see here?" (look at the code or ask for description)
- "What does the user need to decide or enter?"
- "What happens when they proceed?"
- "What could go wrong here?"

As they describe each step, mentally apply the relevant heuristics and note cognitive load signals. Share observations conversationally as you go.

### Phase 3: Synthesis

After walking through, summarize what you found. Group observations by:

1. **Critical issues** — things that block users completely
2. **Friction points** — things that slow users down or cause confusion
3. **Cognitive load hotspots** — places where the user's mental effort is highest
4. **Polish opportunities** — smaller improvements

For each finding, frame it as:
- **What's happening** (the behavior or symptom)
- **Why it's a problem** (the heuristic or cognitive load principle)
- **What could change** (one or more options to explore)

### Phase 4: Discussion

End by asking what resonates and what doesn't:
- "Does any of this match what you've been hearing from users?"
- "Which of these feels most worth tackling first?"
- "Want me to dig deeper into any particular area?"

## Common UX Patterns & Anti-Patterns

| Pattern | Good For | Bad When |
|---------|----------|----------|
| Wizard / Stepper | Complex setup with dependencies between steps | Simple tasks that could be one page |
| Sidebar navigation | Many sections, deep hierarchy | Shallow, simple apps (wastes space) |
| Drag and drop | Reordering, kanban boards | Precise selections, accessibility-critical flows |
| Infinite scroll | Content discovery, social feeds | Finding specific items, e-commerce browsing |
| Hamburger menu | Content sites, mobile | Navigation-heavy apps, power users |
| Modal dialogs | Focused tasks, confirmations | Complex forms, reference data needed from behind the modal |
| Tabs | Grouping related content | Options that need comparison |
| Accordion | Secondary info on demand | Primary content that most users need |
| Progressive disclosure | Complex forms, feature-rich apps | When too many things are hidden — users don't know they exist |
| Toast notifications | Non-blocking feedback | Critical errors, multiple toasts stacking up |

## Cognitive Load Signals — Quick Reference

When you see these in the user's description or code, call them out:

| Signal | Likely Problem |
|--------|---------------|
| "Users keep asking how to X" | Visibility or findability issue |
| "High bounce rate on step 3" | Cognitive load peak — too many decisions at once |
| "Settings is a dumping ground" | Information architecture not matching mental model |
| "Users miss the save button" | Visual hierarchy problem, action not prominent enough |
| "New users take weeks to learn" | Extraneous load too high, not enough progressive disclosure |
| "Power users complain it's slow" | Lack of efficiency shortcuts (heuristic 7) |
| "Users don't notice new features" | Discoverability problem, lack of system status |
| "Forms lose data on error" | Violation of user control and error recovery |
| "Confirmation dialogs everywhere" | Over-correction — trust your users more |
| "We get tickets for things already in the UI" | Recognition vs recall — info is there but not visible |

## Red Flags

Quick signals that a flow needs work:

- More than 5 steps in a linear wizard
- More than 7 items in a top navigation
- Deep navigation (3+ levels) without breadcrumbs
- No search on data-heavy pages
- More than 3 modals deep
- Same action discovered 3 different ways in the UI
- Multiple UI frameworks or inconsistent component patterns in the code
- No loading states, empty states, or error states in the code
- Custom UI patterns where standard HTML elements would work
- More than 12 settings on one page
- No undo or confirmation on delete (unless delete is always reversible)
- Fields with no constraints or validation shown upfront
- Navigation hidden behind hover or gesture-only interactions
- Important information only visible after scrolling without visible scroll cues

## Example Conversation

**User**: "My SaaS app has this project setup wizard. It's 8 steps and users keep abandoning at step 5. Can you look at the code?"

**You** (applying the skill): "Let me look at the wizard component. First, 8 steps is a lot — that's already a red flag for cognitive load. Let me understand who's going through this..."

[Read the code, look at the component structure, routing, state management]

"The wizard uses a stepper component at the top showing all 8 steps. Looking at the code, steps 4-5 are heavy — step 4 is API key configuration (intrinsic load) and step 5 is team member invitations with inline search. That's a cognitive load peak right there.

A few things I notice:
1. **Step indicator overload** (Heuristic 3): Showing all 8 steps upfront tells the user 'this will take a while' — which is honest, but also intimidating. Consider progressive disclosure: group related steps and show phases instead of individual steps.
2. **Step 5 invites** (Heuristic 6): The user has to search for team members one at a time. If they have 15 team members, that's 15 repeated searches. Can you bulk-import or copy-paste emails?
3. **No save & continue** (Heuristic 3): Looking at the state management, if a user closes the wizard, their progress is lost. Can you save partial progress?
4. **Step 4 API keys** (Cognitive load): This is intrinsically complex. Can you auto-detect or provide a 'test connection' button upfront so the user gets feedback before completing the step?

What resonates most here? I'd prioritize the save & continue — losing progress is a critical issue. The rest depends on your drop-off data."
```

## Verification

After conducting an audit conversation, ensure you've covered:

- [ ] Understood who the users are and their goals
- [ ] Walked through the flow step by step
- [ ] Applied relevant Nielsen heuristics naturally (not checklisted)
- [ ] Identified cognitive load hotspots
- [ ] Surfaced at least one critical or major issue (or confirmed the flow is solid)
- [ ] Offered concrete options, not just problems
- [ ] Asked the user for their perspective and priorities
