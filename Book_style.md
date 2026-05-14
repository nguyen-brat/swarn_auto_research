# Guideline: Good Technical AI Handbook Structure

## Goal
Write a practical technical book that teaches one AI topic clearly. The book should help readers understand the field, compare methods, apply them, and know their limitations.

## Standard Book Taxonomy

```text
00_preface.md
01_motivating_intro.md
02_core_concepts.md
03_goals.md
04_method_taxonomy.md
05_shared_examples.md

part_1_interpretable_or_basic_methods/
part_2_local_or_component_methods/
part_3_global_or_system_methods/
part_4_model_specific_or_advanced_methods/
part_5_evaluation_and_outlook/

appendices/
````

---

# 00. Preface

## Purpose

Explain what the book is about and who should read it.

## Include

* Book topic and scope.
* Target audience.
* Required background.
* What the book covers.
* What the book does not cover.
* How to read the book.
* Version or edition notes if needed.

## Style

Short, clear, practical.

---

# 01. Motivating Introduction

## Purpose

Make the reader care about the topic.

## Include

* Real-world story, failure case, or motivating example.
* Why the topic matters.
* What problems appear without this field.
* Main questions the book will answer.
* High-level preview of the book.

## Style

Start with a concrete story before definitions.

---

# 02. Core Concepts

## Purpose

Build the vocabulary needed for the rest of the book.

## Include

* Key terms and definitions.
* Differences between similar terms.
* Basic assumptions.
* Common confusion points.
* Short examples for each concept.

## Style

Explain simply first. Add technical detail later.

---

# 03. Goals

## Purpose

Explain what the reader wants to achieve by using this field.

## Include

* Main practical goals.
* Why each goal matters.
* Which types of methods help each goal.
* Trade-offs between goals.

## Example Goal Categories

* Improve model/system quality.
* Understand model/system behavior.
* Justify decisions.
* Discover insights.
* Reduce risk.
* Improve deployment reliability.

---

# 04. Method Taxonomy

## Purpose

Give the reader a map of the field before detailed chapters.

## Include

* Main method families.
* How families differ.
* Local vs global methods, if useful.
* Model-specific vs model-agnostic methods, if useful.
* Simple vs advanced methods.
* A table comparing method families.
* Explanation of blurry boundaries.

## Style

This chapter should organize the field, not explain every method deeply.

---

# 05. Shared Examples

## Purpose

Create common examples used across later chapters.

## Include

* Datasets, tasks, or scenarios.
* Baseline models or systems.
* Evaluation metrics.
* Example inputs and outputs.
* Why these examples are useful.
* Known simplifications or assumptions.

## Style

Use the same examples repeatedly so readers can compare methods.

---

# Part 1. Basic / Interpretable / Foundational Methods

## Purpose

Explain methods that are simple, transparent, or historically foundational.

## Include

Each chapter should cover:

* What the method is.
* Why it is useful.
* Core intuition.
* Basic theory.
* Example.
* Strengths.
* Limitations.
* When to use it.

## Examples

* Linear models.
* Rule-based methods.
* Decision trees.
* Classical pipelines.
* Simple baselines.

---

# Part 2. Local / Component-Level Methods

## Purpose

Explain methods that analyze one prediction, one sample, one module, or one local behavior.

## Include

* What local question the method answers.
* How the method works around one example.
* How to interpret the result.
* Stability and reliability issues.
* Failure cases.

## Examples

* Local explanations.
* Counterfactuals.
* Instance-level analysis.
* Component-level diagnostics.

---

# Part 3. Global / System-Level Methods

## Purpose

Explain methods that describe overall system behavior.

## Include

* What global pattern the method reveals.
* Required data or model access.
* How to summarize results.
* How to compare models or systems.
* Practical limitations.

## Examples

* Feature importance.
* Global behavior plots.
* Surrogate models.
* Dataset-level analysis.
* System-level evaluation.

---

# Part 4. Model-Specific / Advanced Methods

## Purpose

Explain methods designed for specific architectures or advanced systems.

## Include

* Architecture background.
* What internal component is analyzed.
* What signals or representations mean.
* How the method differs from general methods.
* Practical risks and limitations.

## Examples

* Neural network interpretation.
* Transformer analysis.
* Representation analysis.
* Latent space analysis.
* Modality-specific methods.

---

# Part 5. Evaluation and Outlook

## Purpose

Explain how to judge methods and where the field is going.

## Include

* How to evaluate method quality.
* Human evaluation.
* Automatic metrics.
* Fidelity, stability, robustness, usefulness.
* Open problems.
* Future research directions.
* Practical deployment advice.

## Style

Be critical. Explain what is still unresolved.

---

# Appendices

## Purpose

Store background information that supports the main chapters.

## Include

* Basic ML/AI terms.
* Math notation.
* Dataset details.
* Software libraries.
* Implementation notes.
* References.
* Glossary.

## Style

Reference-style, concise, easy to search.

---

# Standard Method Chapter Template

Use this for every method chapter:

```markdown
# Method Name

## Summary
Explain the method in 2–5 sentences.

## Motivation
Explain why the method exists and what problem it solves.

## Intuition
Give a simple mental model or analogy.

## Theory
Explain the formal idea, assumptions, equations, or objective.

## Algorithm
Describe the method step by step.

## Worked Example
Apply it to a realistic example.

## Interpretation
Explain how to read the output.

## Strengths
Explain when the method works well.

## Limitations
Explain failure cases, assumptions, cost, instability, or misleading uses.

## Practical Guidance
Explain when to use it and when not to use it.

## Related Methods
Compare with nearby alternatives.
```

---

# Standard Family Chapter Template

Use this for method-family chapters:

```markdown
# Method Family Name

## Summary
Define the family in simple terms.

## Motivation
Explain why this family exists.

## Core Idea
Explain the shared intuition.

## Common Pipeline
Describe the common workflow or architecture.

## Main Variants
Compare important variants.

## Representative Methods
List key methods and what each contributes.

## Strengths
Explain where the family is useful.

## Limitations
Explain common weaknesses.

## When to Use
Give practical decision guidance.

## Related Families
Compare with other families.
```

---

# Writing Rules

* Start with intuition before math.
* Use concrete examples before abstract discussion.
* Repeat the same structure across chapters.
* Make each chapter readable independently.
* Explain outputs, not only methods.
* Compare related methods.
* Include strengths and limitations.
* Avoid hype.
* Avoid paper-by-paper summaries.
* Write like a practical teacher, not like a dense survey paper.

---

# Success Criteria

A good chapter lets the reader answer:

* What is this?
* Why does it matter?
* How does it work?
* How do I use it?
* How do I interpret the result?
* When should I use it?
* When should I avoid it?
* What can go wrong?
* What alternatives exist?