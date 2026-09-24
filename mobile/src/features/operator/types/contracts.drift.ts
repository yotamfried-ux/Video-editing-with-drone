// Compile-time drift guard between the hand-maintained mobile contract mirror
// and the web-api source of truth. Checked by `npm run type-check` only; never
// imported by the app, so Metro does not bundle it. Each line asserts that a
// value the server can send is accepted by the type the app consumes it as.
// If a line fails, update ./contracts.ts to match
// web-api/src/types/operator-contracts.ts (the server may be stricter, never looser).
import type * as Server from '../../../../../web-api/src/types/operator-contracts';
import type * as App from './contracts';

type ServerFitsApp<S, A> = [S] extends [A] ? true : false;
type Assert<T extends true> = T;

type _ApproveDraftResponse = Assert<ServerFitsApp<Server.ApproveDraftResponse, App.ApproveDraftResponse>>;
type _DeliveryStatusResponse = Assert<ServerFitsApp<Server.DeliveryStatusResponse, App.DeliveryStatusResponse>>;
type _DiscoverDiagnosticReel = Assert<ServerFitsApp<Server.DiscoverDiagnosticReel, App.DiscoverDiagnosticReel>>;
type _DiscoverDiagnosticSession = Assert<ServerFitsApp<Server.DiscoverDiagnosticSession, App.DiscoverDiagnosticSession>>;
type _DiscoverDiagnosticsResponse = Assert<ServerFitsApp<Server.DiscoverDiagnosticsResponse, App.DiscoverDiagnosticsResponse>>;
type _DraftFeedbackRequest = Assert<ServerFitsApp<Server.DraftFeedbackRequest, App.DraftFeedbackRequest>>;
type _DraftFeedbackResponse = Assert<ServerFitsApp<Server.DraftFeedbackResponse, App.DraftFeedbackResponse>>;
type _DraftFeedbackRow = Assert<ServerFitsApp<Server.DraftFeedbackRow, App.DraftFeedbackRow>>;
type _DraftPublishabilityAuthority = Assert<ServerFitsApp<Server.DraftPublishabilityAuthority, App.DraftPublishabilityAuthority>>;
type _DraftRow = Assert<ServerFitsApp<Server.DraftRow, App.DraftRow>>;
type _DraftsResponse = Assert<ServerFitsApp<Server.DraftsResponse, App.DraftsResponse>>;
type _OperatorErrorResponse = Assert<ServerFitsApp<Server.OperatorErrorResponse, App.OperatorErrorResponse>>;
type _OperatorFeedbackEvent = Assert<ServerFitsApp<Server.OperatorFeedbackEvent, App.OperatorFeedbackEvent>>;
type _OperatorReelRow = Assert<ServerFitsApp<Server.OperatorReelRow, App.OperatorReelRow>>;
type _OperatorReelsResponse = Assert<ServerFitsApp<Server.OperatorReelsResponse, App.OperatorReelsResponse>>;
type _OperatorSuggestion = Assert<ServerFitsApp<Server.OperatorSuggestion, App.OperatorSuggestion>>;
type _OperatorSupportResponse = Assert<ServerFitsApp<Server.OperatorSupportResponse, App.OperatorSupportResponse>>;
type _OperatorSupportTicket = Assert<ServerFitsApp<Server.OperatorSupportTicket, App.OperatorSupportTicket>>;
type _PipelineDispatchResponse = Assert<ServerFitsApp<Server.PipelineDispatchResponse, App.PipelineDispatchResponse>>;
type _PipelineResetResponse = Assert<ServerFitsApp<Server.PipelineResetResponse, App.PipelineResetResponse>>;
type _PipelineRunsResponse = Assert<ServerFitsApp<Server.PipelineRunsResponse, App.PipelineRunsResponse>>;
type _PipelineStatusResponse = Assert<ServerFitsApp<Server.PipelineStatusResponse, App.PipelineStatusResponse>>;
type _ReprocessListResponse = Assert<ServerFitsApp<Server.ReprocessListResponse, App.ReprocessListResponse>>;
type _ReprocessRow = Assert<ServerFitsApp<Server.ReprocessRow, App.ReprocessRow>>;
type _ReprocessSubmitResponse = Assert<ServerFitsApp<Server.ReprocessSubmitResponse, App.ReprocessSubmitResponse>>;

// Same shapes under different names on each side.
type _PipelineStatusFromServer = Assert<ServerFitsApp<Server.PipelineStatusRow, App.PipelineStatus>>;
type _PipelineRunFromServer = Assert<ServerFitsApp<Server.PipelineRunRow, App.PipelineRun>>;
type _DeliveryRunFromServer = Assert<ServerFitsApp<Server.DeliveryRunRow, App.DeliveryRun>>;
type _OperatorUploadInitResponseFromServer = Assert<ServerFitsApp<Server.UploadInitResponse, App.OperatorUploadInitResponse>>;

export {};
