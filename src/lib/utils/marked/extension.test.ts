import { describe, expect, it } from 'vitest';
import { marked } from 'marked';

import markedExtension from './extension';

describe('details extension', () => {
	it('parses details blocks with attributes as details tokens', () => {
		marked.use(markedExtension());

		const tokens = marked.lexer(
			'<details type="deep_job" state="queued" title="Deep job" job_id="job-123">\n' +
				'<summary>Глубокий анализ оборудования принят как deep-job.</summary>\n' +
				'</details>\n'
		);

		expect(tokens).toHaveLength(1);
		expect(tokens[0]).toMatchObject({
			type: 'details',
			summary: 'Глубокий анализ оборудования принят как deep-job.',
			attributes: {
				type: 'deep_job',
				state: 'queued',
				title: 'Deep job',
				job_id: 'job-123'
			}
		});
	});
});
