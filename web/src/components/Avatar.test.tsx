import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AVATAR_TONES, avatarTone } from '../lib/avatarTone';
import { Avatar } from './Avatar';

describe('Avatar colour', () => {
  it('W1b/W2b regression: the colour comes from the person id, not from the position in the list', () => {
    const ids = ['p-peter', 'p-jana', 'p-marek', '6f1c2a90-3b1e-4d7a-9f0e-2a4b5c6d7e8f'];
    const before = ids.map(avatarTone);
    const after = [...ids].reverse().map(avatarTone).reverse();
    expect(after).toEqual(before);
    for (const id of ids) {
      const { container, unmount } = render(<Avatar initials="X" seed={id} size={32} />);
      expect(container.firstElementChild).toHaveClass(avatarTone(id));
      unmount();
    }
  });

  it('always picks a palette token and spreads ids over the palette', () => {
    const used = new Set(Array.from({ length: 200 }, (_, i) => avatarTone(`person-${i}`)));
    for (const tone of used) expect(AVATAR_TONES).toContain(tone);
    expect(used.size).toBe(AVATAR_TONES.length);
  });
});
