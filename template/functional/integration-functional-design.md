\# Integration Functional Design

\## 1. Overview

\### 1.1 Purpose

Describe the purpose of this integration and the business capability or product it supports.

\### 1.2 Business Value

Explain the value delivered by the integration (outcomes, KPIs, user impact).

\### 1.3 Intended Audience

\- Product Owner

\- Business Stakeholders

\- Solution / Integration Architects

\- Delivery & QA Teams

\---

\## 2. Scope & Context

\### 2.1 In-Scope

List systems, processes, and data flows included.

\### 2.2 Out-of-Scope

Explicitly list exclusions.

\### 2.3 Assumptions & Constraints

\- Business assumptions

\- Regulatory constraints

\- Technical constraints

\---

\## 3. Actors & Systems

| System | Role | Description |

|------|-----|-------------|

| Source System | Producer | |

| Target System | Consumer | |

| Middleware / Platform | Broker | |

\---

\## 4. Business Process Across Systems

\### 4.1 End-to-End Flow

High-level description of the cross-system process.

\### 4.2 Triggering Events

\- Event / Action

\- Frequency

\- Source of truth

\### 4.3 Happy Path

Step-by-step description of the nominal flow.

\### 4.4 Alternate / Exception Paths

Describe key alternative scenarios.

\---

\## 5. Functional Scenarios

| ID | Scenario | Trigger | Expected Outcome |

|----|----------|--------|------------------|

| FS-01 | | | |

\---

\## 6. Data Objects (Functional View)

\### 6.1 Business Entities

| Entity | Description | System of Record |

|-------|------------|------------------|

\### 6.2 CRUD Responsibility

Clarify ownership and lifecycle per system.

\---

\## 7. Integration Rules

\### 7.1 Business Rules

\- Validation rules

\- Conditional logic

\### 7.2 Idempotency & Consistency

Rules to prevent duplicates and inconsistencies.

\---

\## 8. Error Scenarios (Functional)

| Error Type | Description | Expected Handling |

|-----------|------------|-------------------|

\---

\## 9. Non-Functional Considerations (Functional View)

\- Expected volumes

\- SLA / business criticality

\- Data classification (Public / Internal / Confidential)

\---

\## 10. Dependencies, Risks & Open Points

\### 10.1 Dependencies

\- External teams

\- Third-party systems

\### 10.2 Risks

| Risk | Impact | Mitigation |

|------|--------|-----------|

\### 10.3 Open Points

List unresolved items.