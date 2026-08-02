import { ResourceWorkbench } from "./resource-workbench";

export default async function ResourcePage({
  params,
}: {
  params: Promise<{ resourceId: string }>;
}) {
  const { resourceId } = await params;
  return <ResourceWorkbench resourceId={resourceId} />;
}
