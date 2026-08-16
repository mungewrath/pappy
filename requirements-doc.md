# Pappy - Payroll manager for household nanny

## Functional requirements

- Core payroll
    - Be able to specify pay rate for nanny
    - Auto populate hours based on a configured default
    - Allow modification based on that week
    - Calculate withholding and pay stub information
- Audit and reimbursement
    - Be able to view historical data for tax purposes
    - Generate FSA receipts
    - Generate Schedule H for tax filing
- Reminders
    - Weekly pay
    - Quarterly estimated payments
    - Send W2 / Overtime premium / other documents to employee during tax season
    - Links to standard IRS guidance during tax season, to check for changes
- User Experience
    - Support for login from mobile or desktop

## Architectural requirements

- Low-cost architecture on AWS, using serverless technologies with zero minimum cost
- User authentication must protect the application

## Open questions

- Are these forms needed for the scope of one employee?
    - W3
    - Washington State Employment Security Department EAMS Authorization Request Form
    - Form 2848
    - Form SS4
- Other use cases missing for managing payroll and taxes?