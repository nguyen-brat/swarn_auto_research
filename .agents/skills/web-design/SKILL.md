---
name: web-design
description: Use when building, redesigning, styling, or refining frontend components, pages, applications, dashboards, interfaces, visual systems, or interactive web experiences.
---

# Web Design

## Goal
Create distinctive, production-grade frontend interfaces with a clear aesthetic point of view. Avoid generic "AI slop": default typography, predictable layouts, purple gradients on white, bland cards, and interchangeable SaaS surfaces.

This skill guides design judgment and implementation. It does not override repository, product, accessibility, or framework constraints.

## Before Coding
Commit to a specific direction before writing UI code:

- **Purpose**: What problem does this interface solve, and who uses it?
- **Tone**: Pick a concrete aesthetic, such as brutally minimal, maximalist chaos, retro-futuristic, organic, luxury/refined, playful, editorial, brutalist, art deco, soft/pastel, or industrial/utilitarian.
- **Constraints**: Framework, performance, accessibility, responsiveness, browser support, and existing design system.
- **Differentiation**: Name the memorable design idea: the one visual or interaction choice someone will remember.

If the user gives no aesthetic direction, choose one that fits the domain and state it briefly before implementation.

## Design Rules
- **Typography**: Avoid default-safe choices like Arial, Roboto, Inter, and unstyled system stacks unless the existing product requires them. Pair a characterful display face with a readable body face when fonts are available.
- **Color**: Use CSS variables for theme tokens. Commit to a cohesive palette with dominant colors and sharp accents instead of evenly distributed timid colors.
- **Motion**: Prefer purposeful CSS motion. One strong orchestrated reveal, stagger, transition, or hover system is better than scattered effects. Respect `prefers-reduced-motion`.
- **Composition**: Use intentional space, asymmetry, overlap, density, diagonal flow, or grid-breaking elements when they support the concept.
- **Atmosphere**: Add depth through contextual details: texture, grain, geometric patterns, layered transparency, strong shadows, custom borders, or background treatments that match the concept.
- **Functionality**: Build real working UI states and interactions, not decorative mockups. Controls must be usable, responsive, and accessible.

## Avoid
- Cliched purple/blue gradients on white.
- Generic centered hero plus card grids when the task calls for an application or tool.
- Reusing the same fashionable font or palette across unrelated designs.
- Decorative effects that reduce readability, performance, or accessibility.
- Visible instructional copy that explains the UI instead of making the UI clear.
- Extra features, abstractions, or theming systems that the user did not ask for.

## Implementation Checklist
1. Identify the existing frontend stack and local style conventions.
2. State the chosen aesthetic direction in one short sentence.
3. Implement the smallest complete working interface that satisfies the request.
4. Verify responsive layout, text fit, interactive states, accessibility basics, and reduced-motion behavior.
5. Run the relevant formatter, typecheck, tests, or local preview command when available.

## Success
- The interface works, not just looks like a screenshot.
- The visual system is cohesive and memorable.
- Typography, color, spacing, motion, and details all support the same concept.
- The implementation fits the repo's patterns and avoids unrelated refactors.
