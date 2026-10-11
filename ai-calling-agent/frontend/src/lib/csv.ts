/** Column names the importer recognises, in the order people expect them. */
const TEMPLATE_HEADERS = ["name", "phone", "email", "company", "notes"];

const SAMPLE_ROWS = [
  [
    "Ravi Kumar",
    "+919876543210",
    "ravi@example.com",
    "Kumar Traders",
    "Asked for a callback",
  ],
  ["Neha Gupta", "9876543211", "neha@example.com", "Gupta Exports", ""],
];

function toCsvCell(value: string): string {
  // Quote anything containing a comma, quote or newline; double any inner quotes.
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

export function leadTemplateCsv(): string {
  return [TEMPLATE_HEADERS, ...SAMPLE_ROWS]
    .map((row) => row.map(toCsvCell).join(","))
    .join("\n");
}

/** Triggers a browser download without a round trip to the server. */
export function downloadCsv(filename: string, content: string): void {
  // The BOM makes Excel open UTF-8 correctly, which matters for Indian names.
  const blob = new Blob([`\uFEFF${content}`], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
