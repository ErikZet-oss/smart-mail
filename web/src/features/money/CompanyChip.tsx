import { useQuery } from '@tanstack/react-query';
import { Building2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { customerKey, fetchCustomer } from './moneyApi';

/** W3b: chip with the matched Money company next to the sender; a click opens the Zákazník panel (Figma 36:31480). */
export function CompanyChip({ messageId, onOpen }: { messageId: string; onOpen: () => void }) {
  const { t } = useTranslation();
  const match = useQuery({ queryKey: customerKey(messageId), queryFn: () => fetchCustomer(messageId), retry: false });
  const company = match.data?.company;
  if (!company) return null;
  return (
    <button
      type="button"
      onClick={onOpen}
      title={t('money.customer.openCard')}
      data-testid="company-chip"
      className="type-small ml-2 inline-flex h-6 max-w-[220px] items-center gap-1 rounded-full border border-border-default bg-bg-subtle px-2 align-middle text-text-primary hover:bg-bg-muted"
    >
      <Building2 size={14} aria-hidden="true" className="shrink-0 text-text-secondary" />
      <span className="truncate">{company.name}</span>
    </button>
  );
}
