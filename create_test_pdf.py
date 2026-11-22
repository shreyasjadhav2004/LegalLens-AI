"""Create a test employment contract PDF for pipeline testing (uses fpdf2)."""
from fpdf import FPDF
import sys


def create_test_pdf(path: str):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(20, 20, 20)

    # Title
    pdf.set_font('Helvetica', 'B', 14)
    pdf.cell(0, 10, 'EMPLOYMENT AGREEMENT', ln=True, align='C')
    pdf.ln(4)

    pdf.set_font('Helvetica', '', 10)

    contract_body = (
        "This Employment Agreement is entered into as of January 1, 2024, "
        "between TechCorp Inc. (Company) and John Smith (Employee).\n\n"

        "1. POSITION AND DUTIES\n"
        "Employee is hired as Software Engineer. Employee will report to the CTO. "
        "This is a full-time position based in San Francisco, CA.\n\n"

        "2. COMPENSATION AND BENEFITS\n"
        "Employee shall receive a base salary of USD 0 per year. "
        "This is an unpaid internship. No benefits are provided during this period.\n\n"

        "3. TERM OF EMPLOYMENT\n"
        "This agreement commences January 1, 2024 and continues for 6 months, "
        "expiring June 30, 2024.\n\n"

        "4. CONFIDENTIALITY\n"
        "Employee agrees to keep all Company information strictly confidential. "
        "This obligation survives termination indefinitely.\n\n"

        "5. NON-COMPETE\n"
        "Employee shall not engage in any competing business activity for 24 months "
        "after termination, anywhere in the United States or globally. "
        "This includes any indirect involvement or advisory roles.\n\n"

        "6. INTELLECTUAL PROPERTY\n"
        "All work product, inventions, and ideas created by Employee, whether "
        "during work hours or personal time, belong exclusively to the Company.\n\n"

        "7. TERMINATION\n"
        "Company may terminate this agreement without cause with only 7 days notice. "
        "Employee must provide 30 days written notice to resign. "
        "Company shall have no severance obligation upon termination.\n\n"

        "8. LIMITATION OF LIABILITY\n"
        "In no event shall either party be liable for any amount exceeding "
        "one month of compensation (effectively USD 0).\n\n"

        "9. DISPUTE RESOLUTION\n"
        "All disputes shall be resolved by binding arbitration in California.\n\n"

        "10. GOVERNING LAW\n"
        "This agreement is governed by the laws of the State of California. "
        "Jurisdiction: Santa Clara County, California.\n\n"

        "IN WITNESS WHEREOF the parties have executed this agreement.\n\n"
        "TechCorp Inc.: ________________________  Date: January 1, 2024\n"
        "John Smith:    ________________________  Date: January 1, 2024"
    )

    pdf.multi_cell(0, 6, contract_body)
    pdf.output(path)
    print(f"Created: {path}")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "input_contracts/test_employment.pdf"
    create_test_pdf(out)
