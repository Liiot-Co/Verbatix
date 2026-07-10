from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()


class MarketStudy(Base):
    __tablename__ = "market_studies"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    client = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    nets = relationship("Net", back_populates="study")
    codes = relationship("Code", back_populates="study")
    rounds = relationship("Round", back_populates="study")


class Net(Base):
    __tablename__ = "nets"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    study_id = Column(Integer, ForeignKey("market_studies.id"), nullable=False)
    study = relationship("MarketStudy", back_populates="nets")
    codes = relationship("Code", back_populates="net")


class Code(Base):
    __tablename__ = "codes"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    study_id = Column(Integer, ForeignKey("market_studies.id"), nullable=False)
    net_id = Column(Integer, ForeignKey("nets.id"), nullable=True)
    keywords = Column(Text, nullable=True)
    study = relationship("MarketStudy", back_populates="codes")
    net = relationship("Net", back_populates="codes")
    __table_args__ = (UniqueConstraint("study_id", "name", name="uq_code_study_name"),)


class ResponseCode(Base):
    __tablename__ = "response_codes"
    id = Column(Integer, primary_key=True)
    response_id = Column(Integer, ForeignKey("survey_responses.id"), nullable=False)
    code_id = Column(Integer, ForeignKey("codes.id"), nullable=False)
    confidence = Column(Float, default=0.0)
    origin = Column(String, default="auto")
    response = relationship("SurveyResponse", back_populates="codes")
    code = relationship("Code")
    __table_args__ = (UniqueConstraint("response_id", "code_id", name="uq_response_code"),)


class Round(Base):
    __tablename__ = "rounds"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    study_id = Column(Integer, ForeignKey("market_studies.id"), nullable=True)
    responses = relationship("SurveyResponse", back_populates="round", cascade="all, delete-orphan")
    study = relationship("MarketStudy", back_populates="rounds")


class OfficialBrand(Base):
    __tablename__ = "official_brands"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    variations = relationship("BrandVariation", back_populates="brand")


class BrandVariation(Base):
    __tablename__ = "brand_variations"
    id = Column(Integer, primary_key=True)
    variation_text = Column(String, nullable=False, index=True)
    official_brand_id = Column(Integer, ForeignKey("official_brands.id"))
    brand = relationship("OfficialBrand", back_populates="variations")


class SurveyResponse(Base):
    __tablename__ = "survey_responses"
    id = Column(Integer, primary_key=True)
    round_id = Column(Integer, ForeignKey("rounds.id"), nullable=False)
    original_text = Column(Text, nullable=False)
    extracted_term = Column(String)
    confidence = Column(Float, default=0.0)
    status = Column(String, default="requires_human")
    official_brand_id = Column(Integer, ForeignKey("official_brands.id"), nullable=True)
    external_row_id = Column(String, nullable=True)
    round = relationship("Round", back_populates="responses")
    brand = relationship("OfficialBrand")
    codes = relationship("ResponseCode", back_populates="response", cascade="all, delete-orphan")
