import { describe, expect, it } from 'vitest';

import { addToField, contactRows, emailsIn, selectAllState, toggleAll, type PickEntry } from './addressPicker';

const e = (email: string, name = email.split('@')[0] ?? ''): PickEntry => ({
  key: email.toLowerCase(),
  name,
  email,
  organization: null,
});

describe('W4g address picker (#203)', () => {
  it('reads e-mails from a field with names', () => {
    expect([...emailsIn('Ján Novák <Jan@ABC.sk>, eva@y.sk; zle')]).toEqual(['jan@abc.sk', 'eva@y.sk']);
  });

  it('adds to Komu without duplicates against Komu, Kópia and Skrytá kópia', () => {
    const fields = { to: 'jan@abc.sk', cc: 'Eva <eva@y.sk>', bcc: 'tajne@z.sk' };
    const out = addToField(fields, 'to', [
      e('JAN@abc.sk'),
      e('eva@y.sk'),
      e('tajne@z.sk'),
      e('nova@x.sk', 'Nová, Osoba'),
      e('nova@x.sk'),
    ]);
    expect(out.added).toBe(1);
    expect(out.fields.to).toBe('jan@abc.sk, Nová Osoba <nova@x.sk>');
    expect(out.fields.cc).toBe(fields.cc);
  });

  it('adding into an empty Kópia fills it (the field is then shown)', () => {
    const out = addToField({ to: '', cc: '', bcc: '' }, 'cc', [e('a@x.sk'), e('b@x.sk')]);
    expect(out.fields.cc).toBe('a <a@x.sk>, b <b@x.sk>');
    expect(out.added).toBe(2);
  });

  it('select-all is tri-state and keeps the selection of other address books', () => {
    const other = e('iny@adresar.sk');
    const first = e('a@x.sk');
    const visible = [first, e('b@x.sk')];
    let sel = new Map<string, PickEntry>([[other.key, other]]);
    expect(selectAllState(visible, sel)).toBe(false);
    sel.set(first.key, first);
    expect(selectAllState(visible, sel)).toBe('mixed');
    sel = toggleAll(visible, sel);
    expect(selectAllState(visible, sel)).toBe(true);
    sel = toggleAll(visible, sel);
    expect([...sel.keys()]).toEqual([other.key]);
  });

  it('a contact with two e-mails gives two rows', () => {
    const rows = contactRows({
      display_name: 'Ján Novák',
      organization: 'ABC Stav',
      emails: [{ email: 'jan@abc.sk' }, { email: 'faktury@abc.sk' }, { email: '' }],
    });
    expect(rows.map((r) => r.key)).toEqual(['jan@abc.sk', 'faktury@abc.sk']);
  });
});
