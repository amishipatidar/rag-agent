import docx
doc = docx.Document(r'c:\_My Data\RAGFlow\Documentation\RAGFlowDocumentation.docx')
text = []
for table in doc.tables:
    for row in table.rows:
        text.append(' | '.join([cell.text.replace('\n', ' ') for cell in row.cells]))
open('RAGFlowDoc_tables.txt', 'w', encoding='utf-8').write('\n'.join(text))
